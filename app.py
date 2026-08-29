from flask import Flask, render_template, request, redirect, url_for, abort
import db_setup as db
import llm_client
import image_client
import fact_client


app = Flask(__name__)
RELEVANCE_THRESHOLD = 0.18


@app.before_request
def startup():
    db.init_db()


def _branch_history(tab_id, leaf_id=None):
    branch = db.get_message_branch(tab_id, leaf_id)
    return [{"role": m["role"], "content": m["content"]} for m in branch]


def _user_session_text(messages):
    return " ".join(m["content"] for m in messages if m["role"] == "user")


def _fact_is_relevant(fact):
    if not fact or not fact.get("has_content"):
        return False
    return fact.get("relevance_score", 0) >= RELEVANCE_THRESHOLD


def _latest_caregiver_insights(messages):
    session_text = _user_session_text(messages)
    for msg in reversed(messages):
        if msg["role"] == "assistant" and msg.get("caregiver_notes"):
            filtered = llm_client.filter_caregiver_notes(msg["caregiver_notes"], session_text)
            if filtered:
                return filtered
    return None


def _latest_relevant_fact(messages):
    session_text = _user_session_text(messages)
    for msg in reversed(messages):
        if msg["role"] != "assistant":
            continue
        fact = msg.get("fact_context")
        if not fact or not fact.get("has_content"):
            continue
        if _fact_is_relevant(fact):
            return fact
        combined = (
            f"{fact.get('wiki', {}).get('title', '')} "
            f"{fact.get('wiki', {}).get('extract', '')} "
            f"{fact.get('ddg', '')}"
        )
        rescored = fact_client._relevance_score(session_text, combined)
        if rescored >= RELEVANCE_THRESHOLD:
            fact = dict(fact)
            fact["relevance_score"] = round(rescored, 3)
            return fact
    return None


def _resolve_visual_prompt(ai_response, history):
    if ai_response.get("requires_image"):
        return (ai_response.get("visual_prompt") or "").strip()
    return ""


def _attach_visual(tab_id, assistant_msg_id, visual_prompt, version=1):
    """Create a visual trigger and generate a scene image."""
    visual_prompt = (visual_prompt or "").strip()
    if not visual_prompt:
        return

    visuals = db.get_visuals_for_tab(tab_id)
    existing = next((v for v in visuals if v["source_message_id"] == assistant_msg_id), None)
    vt_id = existing["id"] if existing else db.create_visual_trigger(tab_id, assistant_msg_id, visual_prompt)

    filename = image_client.generate_image(tab_id, visual_prompt, version=version)
    if filename:
        db.update_visual_trigger(vt_id, visual_prompt, filename, version=version)


def _save_assistant_turn(tab_id, parent_id, ai_response, history=None):
    history = history or []
    user_context = _user_session_text(
        [{"role": m["role"], "content": m["content"]} for m in history if m["role"] == "user"]
    )
    filtered_notes = llm_client.filter_caregiver_notes(
        ai_response.get("caregiver_context") or [],
        user_context,
    )
    if len(filtered_notes) < 2:
        filtered_notes = llm_client._default_caregiver_context(ai_response.get("narrative", ""))

    assistant_msg_id = db.add_message(
        tab_id, "assistant",
        ai_response["narrative"],
        choices=ai_response.get("choices"),
        parent_message_id=parent_id,
        caregiver_notes=filtered_notes,
    )

    if user_context or ai_response.get("narrative"):
        fact = fact_client.get_fact_context(
            ai_response.get("visual_prompt", ""),
            ai_response.get("narrative", ""),
            user_context=user_context,
        )
        if fact.get("has_content"):
            db.update_message_fact(assistant_msg_id, fact)

    visual_prompt = _resolve_visual_prompt(ai_response, history)
    if visual_prompt:
        _attach_visual(tab_id, assistant_msg_id, visual_prompt)

    return assistant_msg_id


def _build_scrapbook_story(tab, messages, visuals_map):
    """
    Transform a sealed message branch into a flowing first-person memory story.
    """
    if not messages:
        return []

    story_data = db.get_sealed_story(tab["id"])
    if not story_data:
        story_data = llm_client.generate_first_person_story(tab["title"], messages)
        db.save_sealed_story(tab["id"], story_data)

    sections = []
    opening_text = story_data.get("opening") if isinstance(story_data, dict) else None
    if not opening_text:
        first_user = next((m for m in messages if m["role"] == "user"), None)
        opening_text = first_user["content"] if first_user else f"Memories of {tab['title']}"
    sections.append({"kind": "opening", "text": opening_text})

    # Collect illustrations from visual triggers
    illustrations = []
    for msg in messages:
        if msg["role"] == "assistant":
            visual = visuals_map.get(msg["id"])
            if visual and visual.get("image_filename"):
                caption = visual.get("edited_prompt") or visual.get("llm_generated_prompt") or ""
                illustrations.append({
                    "kind": "illustration",
                    "filename": visual["image_filename"],
                    "caption": caption,
                })

    paragraphs = story_data.get("paragraphs", []) if isinstance(story_data, dict) else [story_data]
    ill_idx = 0
    for para in paragraphs:
        sections.append({"kind": "prose", "text": para})
        if ill_idx < len(illustrations):
            sections.append(illustrations[ill_idx])
            ill_idx += 1

    while ill_idx < len(illustrations):
        sections.append(illustrations[ill_idx])
        ill_idx += 1

    return sections


def _backfill_missing_visuals(tab_id, messages):
    """
    When sealing a tab, ensure images are generated for any existing visual triggers.
    """
    for msg in messages:
        if msg["role"] == "assistant":
            visuals = db.get_visuals_for_tab(tab_id)
            existing_visual = next(
                (v for v in visuals if v["source_message_id"] == msg["id"]),
                None
            )
            if existing_visual and not existing_visual.get("image_filename"):
                prompt = existing_visual.get("edited_prompt") or existing_visual.get("llm_generated_prompt") or ""
                if prompt:
                    filename = image_client.generate_image(tab_id, prompt, version=existing_visual.get("version", 1))
                    if filename:
                        db.update_visual_trigger(
                            existing_visual["id"],
                            prompt,
                            filename,
                            existing_visual.get("version", 1)
                        )


@app.route("/")
def index():
    tabs = db.list_tabs()
    if not tabs:
        return render_template("index.html", tabs=[], active_tab=None, messages=[], visuals_map={})
    return redirect(url_for("view_tab", tab_id=tabs[0]["id"]))


@app.route("/tab/new", methods=["POST"])
def new_tab():
    fragment = request.form.get("fragment", "").strip()
    if not fragment:
        return redirect(url_for("index"))

    title = llm_client.extract_theme(fragment)
    tab_id = db.create_tab(title)

    user_msg_id = db.add_message(tab_id, "user", fragment, parent_message_id=None)

    history = [{"role": "user", "content": fragment}]
    ai_response = llm_client.get_structured_turn(history)
    _save_assistant_turn(tab_id, user_msg_id, ai_response, history)

    return redirect(url_for("view_tab", tab_id=tab_id))


@app.route("/tab/<tab_id>")
def view_tab(tab_id):
    tab = db.get_tab(tab_id)
    if not tab:
        abort(404)

    tabs = db.list_tabs()
    messages = db.get_message_branch(tab_id)
    visuals = db.get_visuals_for_tab(tab_id)
    visuals_map = {v["source_message_id"]: v for v in visuals}
    caregiver_insights = _latest_caregiver_insights(messages)
    relevant_fact = _latest_relevant_fact(messages)
    last_assistant_id = next(
        (m["id"] for m in reversed(messages) if m["role"] == "assistant"), None
    )

    if tab["sealed"]:
        visuals = db.get_visuals_for_tab(tab_id)
        if messages and not any(v.get("image_filename") for v in visuals):
            _backfill_missing_visuals(tab_id, messages)
            visuals = db.get_visuals_for_tab(tab_id)
        visuals_map = {v["source_message_id"]: v for v in visuals}
        story_sections = _build_scrapbook_story(tab, messages, visuals_map)
        return render_template(
            "scrapbook.html",
            active_tab=tab, tabs=tabs,
            story_sections=story_sections,
        )

    return render_template(
        "index.html",
        active_tab=tab, tabs=tabs,
        messages=messages, visuals_map=visuals_map,
        caregiver_insights=caregiver_insights,
        relevant_fact=relevant_fact,
        last_assistant_id=last_assistant_id,
    )


@app.route("/tab/<tab_id>/rename", methods=["POST"])
def rename_tab(tab_id):
    tab = db.get_tab(tab_id)
    if not tab:
        abort(404)
    title = request.form.get("title", "").strip()
    if title:
        db.update_tab_title(tab_id, title)
    return redirect(url_for("view_tab", tab_id=tab_id))


@app.route("/tab/<tab_id>/message", methods=["POST"])
def post_message(tab_id):
    tab = db.get_tab(tab_id)
    if not tab or tab["sealed"]:
        abort(400)

    user_choice = request.form.get("message", "").strip()
    if not user_choice:
        return redirect(url_for("view_tab", tab_id=tab_id))

    branch = db.get_message_branch(tab_id)
    parent_id = branch[-1]["id"] if branch else None

    user_msg_id = db.add_message(
        tab_id, "user", user_choice, parent_message_id=parent_id
    )
    db.increment_depth(tab_id)

    history = _branch_history(tab_id, user_msg_id)
    ai_response = llm_client.get_structured_turn(history)
    _save_assistant_turn(tab_id, user_msg_id, ai_response, history)

    return redirect(url_for("view_tab", tab_id=tab_id))


@app.route("/message/<int:message_id>/delete", methods=["POST"])
def delete_message(message_id):
    msg = db.get_message(message_id)
    if not msg:
        abort(404)
    tab_id = msg["tab_id"]
    tab = db.get_tab(tab_id)
    if not tab or tab["sealed"]:
        abort(400)

    # If deleting an assistant turn, delete its parent user prompt so the entire turn is pruned cleanly
    target_id = message_id
    if msg["role"] == "assistant" and msg.get("parent_message_id"):
        target_id = msg["parent_message_id"]

    db.delete_message_node(target_id)
    db.decrement_depth(tab_id)
    return redirect(url_for("view_tab", tab_id=tab_id))


@app.route("/tab/<tab_id>/visual/<vt_id>/update", methods=["POST"])
def update_visual(tab_id, vt_id):
    """
    Generate or regenerate an image for an existing visual trigger.
    Allows changing the prompt and regenerating repeatedly in place.
    """
    edited_prompt = request.form.get("edited_prompt", "").strip()
    if not edited_prompt:
        return redirect(url_for("view_tab", tab_id=tab_id))

    visuals = db.get_visuals_for_tab(tab_id)
    current = next((v for v in visuals if v["id"] == vt_id), None)
    if not current:
        abort(404)

    new_version = current.get("version", 1) + 1
    filename = image_client.generate_image(tab_id, edited_prompt, version=new_version)
    if filename:
        db.update_visual_trigger(vt_id, edited_prompt, filename, new_version)

    return redirect(url_for("view_tab", tab_id=tab_id))


@app.route("/tab/<tab_id>/message/<int:message_id>/generate_visual", methods=["POST"])
def generate_message_visual(tab_id, message_id):
    """
    Caregiver-triggered image generation when no image was automatically required,
    or when additional prompt desires are provided mid-conversation.
    """
    tab = db.get_tab(tab_id)
    if not tab:
        abort(404)
    prompt = request.form.get("prompt", "").strip()
    if not prompt:
        return redirect(url_for("view_tab", tab_id=tab_id))

    visuals = db.get_visuals_for_tab(tab_id)
    existing = next((v for v in visuals if v["source_message_id"] == message_id), None)

    if existing:
        new_version = existing.get("version", 1) + 1
        filename = image_client.generate_image(tab_id, prompt, version=new_version)
        if filename:
            db.update_visual_trigger(existing["id"], prompt, filename, new_version)
    else:
        vt_id = db.create_visual_trigger(tab_id, message_id, prompt)
        filename = image_client.generate_image(tab_id, prompt, version=1)
        if filename:
            db.update_visual_trigger(vt_id, prompt, filename, 1)

    return redirect(url_for("view_tab", tab_id=tab_id))


@app.route("/tab/<tab_id>/seal", methods=["POST"])
def seal_tab(tab_id):
    tab = db.get_tab(tab_id)
    if not tab:
        abort(404)
    messages = db.get_message_branch(tab_id)
    _backfill_missing_visuals(tab_id, messages)

    # Generate and persist gentle first-person story
    story_data = llm_client.generate_first_person_story(tab["title"], messages)
    db.save_sealed_story(tab_id, story_data)

    # Pre-generate game recall cards
    game_data = llm_client.generate_memory_game(tab["title"], messages)
    if game_data:
        db.save_game_data(tab_id, game_data)

    db.seal_tab(tab_id)
    return redirect(url_for("view_tab", tab_id=tab_id))


@app.route("/tab/<tab_id>/game")
def memory_game(tab_id):
    """Interactive card-based memory recall game for a specific memory."""
    tab = db.get_tab(tab_id)
    if not tab:
        abort(404)

    tabs = db.list_tabs()
    messages = db.get_message_branch(tab_id)

    game_cards = db.get_game_data(tab_id)
    if not game_cards:
        game_cards = llm_client.generate_memory_game(tab["title"], messages)
        if game_cards:
            db.save_game_data(tab_id, game_cards)

    visuals = db.get_visuals_for_tab(tab_id)
    visual_images = [v["image_filename"] for v in visuals if v.get("image_filename")]

    return render_template(
        "game.html",
        active_tab=tab,
        tabs=tabs,
        questions=game_cards,
        visual_images=visual_images,
    )


@app.route("/game")
def game_portal():
    """Portal route from the sidebar: directs to the best memory to play."""
    tabs = db.list_tabs()
    if not tabs:
        return redirect(url_for("index"))
    # Prefer most recent sealed memory, or fallback to first tab
    target = next((t for t in tabs if t.get("sealed")), tabs[0])
    return redirect(url_for("memory_game", tab_id=target["id"]))


if __name__ == "__main__":
    app.run(debug=True)