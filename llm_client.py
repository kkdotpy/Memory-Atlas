import ollama
import re
import json
from prompts import SYSTEM_PROMPT, THEME_SYSTEM, FIRST_PERSON_STORY_SYSTEM, MEMORY_GAME_SYSTEM


def _strip_fences(text):
    """Remove ```json or ``` wrappers that small local models often add."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


## Specifying models and system prompts for the LLM client
MODEL = "mistral:7b"


## Function to call ollama for structured JSON responses (main narrative turns).
def _call_ollama_json(messages, max_tries=2):
    payload = {
        "model": MODEL,
        "messages": messages,
        'format': 'json',   # Force JSON output for structured turns
        "options": {
            "temperature": 0.7
        }
    }

    for attempt in range(max_tries+1):
        try:
            response = ollama.chat(**payload)
            return response.message.content
        except Exception as e:
            if attempt == max_tries:
                raise e
    return None


## Function to call ollama for plain-text responses (theme extraction only).
## Does NOT use format='json' so the model returns a clean plain string.
def _call_ollama_text(messages, max_tries=2):
    payload = {
        "model": MODEL,
        "messages": messages,
        "options": {
            "temperature": 0.3   # Lower temperature for consistent short title output
        }
    }

    for attempt in range(max_tries+1):
        try:
            response = ollama.chat(**payload)
            return response.message.content
        except Exception as e:
            if attempt == max_tries:
                raise e
    return None


## This is to extract a theme from users input for tab name.
## Called just once for each tab and once named doesn't change.
## Uses plain text mode (not JSON) to avoid the model returning a JSON wrapper.
def extract_theme(user_fragment):
    """Single-shot call: returns a 2-3 word title string."""
    messages = [
        {"role": "system", "content": THEME_SYSTEM},
        {"role": "user", "content": user_fragment}
    ]
    try:
        raw = _call_ollama_text(messages)
        title = raw.strip().strip('"').strip("'")
        # Safety cap: don't let a runaway model return a paragraph
        words = title.split()
        return " ".join(words[:4]) if words else "A Memory"
    except Exception:
        return "A Memory"


def is_conversational_filler(text):
    """Detect if user input is purely conversational acknowledgement without scene detail."""
    cleaned = (text or "").strip().lower().strip(".,!?;:'\"-")
    if len(cleaned.split()) <= 2 and cleaned in {
        "yes", "yeah", "yep", "sure", "no", "nope", "maybe", "ok", "okay",
        "thanks", "thank you", "i agree", "right", "good", "fine", "hello", "hi", "hm", "hmm"
    }:
        return True
    if cleaned in {
        "i think so", "i don't know", "i dont know", "not sure", "that sounds nice",
        "that was nice", "it was good", "i think so too", "yes that was nice", "yes it was"
    }:
        return True
    return False


def should_require_image(user_text, visual_prompt=""):
    """
    Careful check whether the user description contains visual scene details
    warranting automated image generation.
    """
    if is_conversational_filler(user_text):
        return False
    if len((user_text or "").strip().split()) < 3:
        return False
    return bool(visual_prompt and len(visual_prompt.split()) >= 3)


def get_structured_turn(conversation_history):
    """
    conversation_history: list of dicts with 'role' ('user'|'assistant') and 'content'.
    Returns: {"narrative": str, "requires_image": bool, "visual_prompt": str, "caregiver_context": [str, ...]}
    Falls back gracefully — never raises to the caller.
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history

    last_error = None
    raw = None
    for attempt in range(3):
        try:
            raw = _call_ollama_json(messages)
            clean = _strip_fences(raw)
            data = json.loads(clean)
            if all(k in data for k in ("narrative", "caregiver_context")):
                if isinstance(data["caregiver_context"], list) and len(data["caregiver_context"]) >= 2:
                    return _normalize_turn(data, conversation_history)
        except Exception as e:
            last_error = e

    # in case of repeated failure, return a safe default
    fallback_narrative = raw if raw else "Let's sit with that thought for a moment."
    return {
        "narrative": fallback_narrative,
        "requires_image": False,
        "visual_prompt": "",  # Don't auto-generate; let caregiver ask
        "caregiver_context": _default_caregiver_context(fallback_narrative),
    }


def _derive_visual_prompt(user_text, narrative):
    """Build a concrete scene descriptor when the model omits visual_prompt."""
    source = (user_text or "").strip()
    if not source:
        return ""
    words = source.split()
    return " ".join(words[:35])


def _normalize_turn(data, conversation_history):
    """Ensure turn validity and properly check whether an image is required."""
    last_user_msg = next((m["content"] for m in reversed(conversation_history) if m["role"] == "user"), "")
    
    raw_req = data.get("requires_image")
    # True if explicitly True, or string 'true'/'yes', or None but visual_prompt was generated
    is_req = raw_req in (True, "true", "True", "yes", "1", 1) or (raw_req is None)
    visual_prompt = (data.get("visual_prompt") or "").strip()
    
    # Filter out dummy placeholder strings
    if visual_prompt.lower() in ("none", "n/a", "null", "empty", "no", "false"):
        visual_prompt = ""

    # Check if user input is genuine memory content vs conversational filler
    if is_conversational_filler(last_user_msg) or len(last_user_msg.split()) < 3 or not visual_prompt:
        data["requires_image"] = False
        data["visual_prompt"] = ""
    else:
        data["requires_image"] = is_req
        data["visual_prompt"] = visual_prompt if is_req else ""
    
    ctx = data.get("caregiver_context", [])
    if not isinstance(ctx, list):
        ctx = [str(ctx)] if ctx else []

    session_text = " ".join(m["content"] for m in conversation_history if m["role"] == "user")
    data["caregiver_context"] = filter_caregiver_notes(
        [str(n).strip() for n in ctx if str(n).strip()][:4],  # Allow up to 4 items
        session_text,
    )
    if len(data["caregiver_context"]) < 2:
        data["caregiver_context"] = _default_caregiver_context(data.get("narrative", ""))
    return data


def generate_first_person_story(tab_title, conversation_history):
    """
    Generate a simple, beautiful, flowing FIRST-PERSON memory story ("I remember...", "My...")
    using simple and heartwarming vocabulary suitable for reminiscence therapy.
    """
    user_turns = [m["content"] for m in conversation_history if m["role"] == "user"]
    if not user_turns:
        return {
            "opening": f"I remember {tab_title}.",
            "paragraphs": ["These cherished moments remain close to my heart."]
        }

    combined_memory = "\n".join([f"- {turn}" for turn in user_turns])
    messages = [
        {"role": "system", "content": FIRST_PERSON_STORY_SYSTEM},
        {"role": "user", "content": f"Memory title: {tab_title}\n\nWhat I shared:\n{combined_memory}"}
    ]

    try:
        raw = _call_ollama_json(messages)
        if raw:
            clean = _strip_fences(raw)
            data = json.loads(clean)
            if "paragraphs" in data and isinstance(data["paragraphs"], list) and len(data["paragraphs"]) > 0:
                paragraphs = [p.strip() for p in data["paragraphs"] if str(p).strip()]
                opening = (data.get("opening") or user_turns[0]).strip()
                return {
                    "opening": opening,
                    "paragraphs": paragraphs
                }
    except Exception as e:
        print(f"[llm_client] LLM story generation error: {e}")

    return _build_rule_based_first_person_story(tab_title, user_turns)


def _build_rule_based_first_person_story(tab_title, user_turns):
    """Warm, simple first-person synthesis fallback when LLM is unavailable."""
    if not user_turns:
        return {"opening": f"Memories of {tab_title}", "paragraphs": []}
    
    opening = user_turns[0].strip()
    paragraphs = []
    
    current_para = []
    for turn in user_turns:
        cleaned = turn.strip()
        if not cleaned:
            continue
        if not re.match(r"^(I|We|My|Our|When I|Whenever|Every|In those days)", cleaned, re.IGNORECASE):
            cleaned = f"I remember {cleaned[0].lower() + cleaned[1:] if len(cleaned) > 1 else cleaned}"
        current_para.append(cleaned)
        if len(current_para) >= 2:
            paragraphs.append(" ".join(current_para))
            current_para = []
            
    if current_para:
        paragraphs.append(" ".join(current_para))
        
    if not paragraphs:
        paragraphs = [opening]
        
    return {
        "opening": opening,
        "paragraphs": paragraphs
    }


def generate_memory_game(tab_title, conversation_history):
    """
    Generate interactive card-based recall game questions grounded strictly
    in what the person mentioned in their sealed memory.
    Guarantees that the correct answer is ALWAYS present in the options.
    """
    user_turns = [m["content"] for m in conversation_history if m["role"] == "user"]
    if not user_turns:
        return []

    combined_memory = "\n".join([f"Memory share {i+1}: {turn}" for i, turn in enumerate(user_turns)])
    messages = [
        {"role": "system", "content": MEMORY_GAME_SYSTEM},
        {"role": "user", "content": f"Memory topic: {tab_title}\n\nUser's exact words:\n{combined_memory}"}
    ]

    try:
        raw = _call_ollama_json(messages)
        if raw:
            clean = _strip_fences(raw)
            data = json.loads(clean)
            cards = data.get("cards", [])
            if isinstance(cards, list) and len(cards) > 0:
                valid_cards = []
                for c in cards:
                    if all(k in c for k in ("question", "options", "answer")):
                        ans = str(c["answer"]).strip()
                        raw_opts = [str(opt).strip() for opt in c["options"] if str(opt).strip()]
                        
                        # Ensure options list has exactly 3 options and ALWAYS includes answer
                        if ans not in raw_opts:
                            raw_opts.insert(0, ans)
                        opts = raw_opts[:3]
                        if len(opts) < 3:
                            opts.append("A quiet moment taking in the view")
                        if len(opts) < 3:
                            opts.append("Sitting down and enjoying the calm breeze")

                        valid_cards.append({
                            "question": str(c["question"]).strip(),
                            "options": opts,
                            "answer": ans,
                            "hint": str(c.get("hint") or "Think back to when you shared this story.").strip(),
                            "celebration": str(c.get("celebration") or "Wonderful! That is exactly what you remembered.").strip()
                        })
                if valid_cards:
                    return valid_cards
    except Exception as e:
        print(f"[llm_client] LLM game generation error: {e}")

    return _build_rule_based_memory_game(tab_title, user_turns)


def _build_rule_based_memory_game(tab_title, user_turns):
    """Build gentle recall cards strictly from user sentences with guaranteed correct option."""
    cards = []
    
    gentle_distractor_pools = [
        ["A quiet walk through a blooming garden", "Looking at old family photo albums"],
        ["The sound of gentle rain on the roof", "A warm cup of tea by the window"],
        ["Riding the morning train with friends", "Sitting under a shady willow tree"],
        ["Cooking dinner together with family", "Listening to music on the radio"]
    ]

    for i, turn in enumerate(user_turns):
        text = turn.strip()
        if len(text) < 8:
            continue
        
        snippet = text[:90] + ("…" if len(text) > 90 else "")
        question = f"In your recollection of '{tab_title}', what did you remember?"
        
        distractors = gentle_distractor_pools[i % len(gentle_distractor_pools)]
        
        # Position answer reliably among the 3 options
        if i % 3 == 0:
            options = [snippet, distractors[0], distractors[1]]
        elif i % 3 == 1:
            options = [distractors[0], snippet, distractors[1]]
        else:
            options = [distractors[0], distractors[1], snippet]
        
        cards.append({
            "question": question,
            "options": options,
            "answer": snippet,
            "hint": f"You were speaking about {tab_title.lower()}.",
            "celebration": "That's it! You remembered your words wonderfully."
        })
        if len(cards) >= 4:
            break

    return cards







def filter_caregiver_notes(notes, session_text):
    """Drop caregiver notes that introduce facts not grounded in the session."""
    if not notes:
        return []
    session_terms = _session_terms(session_text)
    filtered = []
    for note in notes:
        if _is_generic_support_note(note):
            filtered.append(note)
            continue
        note_terms = _session_terms(note)
        if not note_terms:
            continue
        overlap = note_terms & session_terms
        if len(overlap) >= 2:
            filtered.append(note)
    return filtered


def _session_terms(text):
    tokens = re.findall(r"[a-zA-Z']+", (text or "").lower())
    stop = {"that", "this", "with", "from", "have", "were", "been", "they", "what", "when", "where"}
    return {t for t in tokens if len(t) > 3 and t not in stop}


GENERIC_SUPPORT_CHECKER = '''Check if the note is a generic caregiver support suggestion (e.g., 'listen warmly', 'allow pauses') without introducing new facts. Return True if it is generic, False otherwise.
                            For example: "Ask if they remember the area around the river" is generic so return True, but "Ask if they remember a shop named "Miraj Fashion" near that river" is not generic so return False.
                          '''

def _is_generic_support_note(note):
    # markers = (
    #     "listen warmly", "without correcting", "open question", "how it felt",
    #     "how this felt", "allow pauses", "reflect back", "no need to fill",
    #     "gentle", "validation", "encourage", "pause", "silence",
    # )
    # lower = note.lower()
    # return any(m in lower for m in markers)
    # Use the model to check if the note is generic or not
    messages = [
        {"role": "system", "content": GENERIC_SUPPORT_CHECKER},
        {"role": "user", "content": note}
    ]
    try:
        raw = _call_ollama_text(messages)
        result = raw.strip().lower()
        return result == "true"
    except Exception:
        return False


def _default_caregiver_context(narrative):
    return [
        "Listen warmly and reflect back what was shared without correcting or fact-checking details.",
        "Ask gently about sensory details: 'What do you remember about the sounds?' or 'How did it feel?'",
        "Invite them to describe who was nearby or what emotions they associate with this memory.",
        "Allow pauses — there is no need to fill silence or redirect toward facts.",
    ]



## Testing the function
if __name__ == "__main__":
    history = [
        {"role": "user", "content": "I remember walking down to the river every evening."},
        {"role": "assistant", "content": "That sounds peaceful. What did you see there?"},
        {"role": "user", "content": "I saw the sunset reflecting on the water, and sometimes people fishing."},
    ]
    result = get_structured_turn(history)
    print(result)

# import ollama
# import re
# import json


# ### TODO: The visual prompts are being generated even though the user has not provided rich sensory detail.
# ##  TODO: the scrapbook is saving memory but written not as a story in first person.
# ##  TODO: If time is enough adding a simple game which roots itself on images being generated and helps match with the context of what the image is about so that they can exercise their mind.

# def _strip_fences(text):
#     """Remove ```json or ``` wrappers that small local models often add."""
#     text = text.strip()
#     text = re.sub(r"^```(?:json)?\s*", "", text)
#     text = re.sub(r"\s*```$", "", text)
#     return text.strip()


# ## Specifying models and system prompts for the LLM client
# MODEL = "mistral:7b"

# SYSTEM_PROMPT = '''You are the narrative engine for 'The Memory Atlas,' a gentle reminiscence
#                  companion used by a person experiencing memory changes, together with a family member or caregiver.

#                 Your job each turn:
#                 1. Read the full conversation history for this memory thread.
#                 2. Write a short, warm narrative paragraph (3-5 sentences) that reflects back what was shared,
#                 in a validating, non-corrective tone. Never question accuracy — gently follow their lead. Also add a sentence that invites them to share more sensory detail, if they wish. 
#                 Avoid historical facts, dates, place names, or any information not explicitly mentioned by the person sharing. Never invent or assume context.
#                 3. Extract a concise visual prompt descriptor (two sentence, concrete and visual: setting,
#                 objects, era, lighting) suitable for Stable Diffusion, ONLY if the person has shared
#                 rich sensory detail. Otherwise, leave it empty — the caregiver will decide if an image helps.
#                 4. Provide caregiver_context: exactly 3-4 gentle prompts for the caregiver ONLY — open-ended 
#                 questions suggestions for deepening the conversation adding to that previous premise. Do NOT include historical facts, dates, place 
#                 names, or any information not explicitly mentioned by the person sharing. Never invent 
#                 or assume context. These are suggestions the caregiver can use to ask follow-up questions.
#                 Examples: "Ask what they remember about the sounds...", "Invite them to describe who was nearby..."

#                 If the message expresses distress, grief, confusion, or a desire to stop: acknowledge gently in
#                 the narrative, set visual_prompt to empty string, and keep caregiver_context supportive 
#                 and non-redirecting (e.g., "Allow pauses", "Reflect warmth without pushing for more").

#                 Respond with ONLY valid JSON — no preamble, no markdown fences, no explanation:
#                 {"narrative": "string", "visual_prompt": "string", "caregiver_context": ["string","string","string","string"]}

#                 Note: There is NO "choices" field — the three memory starters now live ONLY in caregiver_context 
#                 as guidance for how the caregiver can continue the conversation naturally.
#                 '''

# ## For tabs name — a simpler, separate prompt. Does NOT use JSON format mode so
# ## the model returns a plain string title rather than a JSON object.
# THEME_SYSTEM = """Extract a 2-3 word memory theme title from the user's text.
#                 Return ONLY the title words, no punctuation, no explanation, nothing else.
#                 <Example input> and <Example output> are provided for clarity.
#                 Example input: "I remember walking down to the river every evening."
#                 Example output: River Evening Walks"""



# ## Function to call ollama for structured JSON responses (main narrative turns).
# def _call_ollama_json(messages, max_tries=2):
#     payload = {
#         "model": MODEL,
#         "messages": messages,
#         'format': 'json',   # Force JSON output for structured turns
#         "options": {
#             "temperature": 0.7
#         }
#     }

#     for attempt in range(max_tries+1):
#         try:
#             response = ollama.chat(**payload)
#             return response.message.content
#         except Exception as e:
#             if attempt == max_tries:
#                 raise e
#     return None


# ## Function to call ollama for plain-text responses (theme extraction only).
# ## Does NOT use format='json' so the model returns a clean plain string.
# def _call_ollama_text(messages, max_tries=2):
#     payload = {
#         "model": MODEL,
#         "messages": messages,
#         "options": {
#             "temperature": 0.3   # Lower temperature for consistent short title output
#         }
#     }

#     for attempt in range(max_tries+1):
#         try:
#             response = ollama.chat(**payload)
#             return response.message.content
#         except Exception as e:
#             if attempt == max_tries:
#                 raise e
#     return None


# ## This is to extract a theme from users input for tab name.
# ## Called just once for each tab and once named doesn't change.
# ## Uses plain text mode (not JSON) to avoid the model returning a JSON wrapper.
# def extract_theme(user_fragment):
#     """Single-shot call: returns a 2-3 word title string."""
#     messages = [
#         {"role": "system", "content": THEME_SYSTEM},
#         {"role": "user", "content": user_fragment}
#     ]
#     try:
#         raw = _call_ollama_text(messages)
#         title = raw.strip().strip('"').strip("'")
#         # Safety cap: don't let a runaway model return a paragraph
#         words = title.split()
#         return " ".join(words[:4]) if words else "A Memory"
#     except Exception:
#         return "A Memory"


# def get_structured_turn(conversation_history):
#     """
#     conversation_history: list of dicts with 'role' ('user'|'assistant') and 'content'.
#     Returns: {"narrative": str, "visual_prompt": str, "caregiver_context": [str, ...]}
#     No "choices" field — all guidance is in caregiver_context (display-only, for caregiver's reference).
#     Falls back gracefully — never raises to the caller.
#     """
#     messages = [{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history

#     last_error = None
#     raw = None
#     for attempt in range(3):
#         try:
#             raw = _call_ollama_json(messages)
#             clean = _strip_fences(raw)
#             data = json.loads(clean)
#             if all(k in data for k in ("narrative", "caregiver_context")):
#                 if isinstance(data["caregiver_context"], list) and len(data["caregiver_context"]) >= 2:
#                     return _normalize_turn(data, conversation_history)
#         except Exception as e:
#             last_error = e

#     # in case of repeated failure, return a safe default
#     fallback_narrative = raw if raw else "Let's sit with that thought for a moment."
#     return {
#         "narrative": fallback_narrative,
#         "visual_prompt": "",  # Don't auto-generate; let caregiver ask
#         "caregiver_context": _default_caregiver_context(fallback_narrative),
#     }


# def _derive_visual_prompt(user_text, narrative):
#     """Build a concrete scene descriptor when the model omits visual_prompt."""
#     source = (user_text or narrative or "").strip()
#     if not source:
#         return ""
#     # Prefer the user's own words — they contain the vivid details
#     words = source.split()
#     return " ".join(words[:35])


# def _normalize_turn(data, conversation_history):
#     """Ensure every turn has valid caregiver context. visual_prompt stays empty unless rich detail present."""
#     # Only populate visual_prompt if it was explicitly returned and contains detail
#     visual_prompt = (data.get("visual_prompt") or "").strip()
#     data["visual_prompt"] = visual_prompt  # Keep empty if not provided
    
#     ctx = data.get("caregiver_context", [])
#     if not isinstance(ctx, list):
#         ctx = [str(ctx)] if ctx else []

#     session_text = " ".join(m["content"] for m in conversation_history if m["role"] == "user")
#     data["caregiver_context"] = filter_caregiver_notes(
#         [str(n).strip() for n in ctx if str(n).strip()][:4],  # Allow up to 4 items
#         session_text,
#     )
#     if len(data["caregiver_context"]) < 2:
#         data["caregiver_context"] = _default_caregiver_context(data.get("narrative", ""))
#     return data





# def filter_caregiver_notes(notes, session_text):
#     """Drop caregiver notes that introduce facts not grounded in the session."""
#     if not notes:
#         return []
#     session_terms = _session_terms(session_text)
#     filtered = []
#     for note in notes:
#         if _is_generic_support_note(note):
#             filtered.append(note)
#             continue
#         note_terms = _session_terms(note)
#         if not note_terms:
#             continue
#         overlap = note_terms & session_terms
#         if len(overlap) >= 2:
#             filtered.append(note)
#     return filtered


# def _session_terms(text):
#     tokens = re.findall(r"[a-zA-Z']+", (text or "").lower())
#     stop = {"that", "this", "with", "from", "have", "were", "been", "they", "what", "when", "where"}
#     return {t for t in tokens if len(t) > 3 and t not in stop}


# GENERIC_SUPPORT_CHECKER = '''Check if the note is a generic caregiver support suggestion (e.g., 'listen warmly', 'allow pauses') without introducing new facts. Return True if it is generic, False otherwise.
#                             For example: "Ask if they remember the area around the river" is generic so return True, but "Ask if they remember a shop named "Miraj Fashion" near that river" is not generic so return False.
#                           '''

# def _is_generic_support_note(note):
#     # markers = (
#     #     "listen warmly", "without correcting", "open question", "how it felt",
#     #     "how this felt", "allow pauses", "reflect back", "no need to fill",
#     #     "gentle", "validation", "encourage", "pause", "silence",
#     # )
#     # lower = note.lower()
#     # return any(m in lower for m in markers)
#     # Use the model to check if the note is generic or not
#     messages = [
#         {"role": "system", "content": GENERIC_SUPPORT_CHECKER},
#         {"role": "user", "content": note}
#     ]
#     try:
#         raw = _call_ollama_text(messages)
#         result = raw.strip().lower()
#         return result == "true"
#     except Exception:
#         return False


# def _default_caregiver_context(narrative):
#     return [
#         "Listen warmly and reflect back what was shared without correcting or fact-checking details.",
#         "Ask gently about sensory details: 'What do you remember about the sounds?' or 'How did it feel?'",
#         "Invite them to describe who was nearby or what emotions they associate with this memory.",
#         "Allow pauses — there is no need to fill silence or redirect toward facts.",
#     ]



# ## Testing the function
# if __name__ == "__main__":
#     history = [
#         {"role": "user", "content": "I remember walking down to the river every evening."},
#         {"role": "assistant", "content": "That sounds peaceful. What did you see there?"},
#         {"role": "user", "content": "I saw the sunset reflecting on the water, and sometimes people fishing."},
#     ]
#     result = get_structured_turn(history)
#     print(result)