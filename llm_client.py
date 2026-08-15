import ollama
import re
import json


def _strip_fences(text):
    """Remove ```json or ``` wrappers that small local models often add."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


## Specifying models and system prompts for the LLM client
MODEL = "mistral:7b"

SYSTEM_PROMPT = '''You are the narrative engine for 'The Memory Atlas,' a gentle reminiscence
                 companion used by a person experiencing memory changes, together with a family member or caregiver.

                Your job each turn:
                1. Read the full conversation history for this memory thread.
                2. Write a short, warm narrative paragraph (3-5 sentences) that reflects back what was shared,
                in a validating, non-corrective tone. Never question accuracy — gently follow their lead.
                3. Extract a concise visual prompt descriptor (two sentence, concrete and visual: setting,
                objects, era, lighting) suitable for Stable Diffusion, ONLY if the person has shared
                rich sensory detail. Otherwise, leave it empty — the caregiver will decide if an image helps.
                4. Provide caregiver_context: exactly 3-4 gentle prompts for the caregiver ONLY — open-ended 
                suggestions for deepening the conversation adding to that previous premise. Do NOT include historical facts, dates, place 
                names, or any information not explicitly mentioned by the person sharing. Never invent 
                or assume context. These are suggestions the caregiver can use to ask follow-up questions.
                Examples: "Ask what they remember about the sounds...", "Invite them to describe who was nearby..."

                If the message expresses distress, grief, confusion, or a desire to stop: acknowledge gently in
                the narrative, set visual_prompt to empty string, and keep caregiver_context supportive 
                and non-redirecting (e.g., "Allow pauses", "Reflect warmth without pushing for more").

                Respond with ONLY valid JSON — no preamble, no markdown fences, no explanation:
                {"narrative": "string", "visual_prompt": "string", "caregiver_context": ["string","string","string","string"]}

                Note: There is NO "choices" field — the three memory starters now live ONLY in caregiver_context 
                as guidance for how the caregiver can continue the conversation naturally.
                '''

## For tabs name — a simpler, separate prompt. Does NOT use JSON format mode so
## the model returns a plain string title rather than a JSON object.
THEME_SYSTEM = """Extract a 2-3 word memory theme title from the user's text.
                Return ONLY the title words, no punctuation, no explanation, nothing else.
                <Example input> and <Example output> are provided for clarity.
                Example input: "I remember walking down to the river every evening."
                Example output: River Evening Walks"""



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


def get_structured_turn(conversation_history):
    """
    conversation_history: list of dicts with 'role' ('user'|'assistant') and 'content'.
    Returns: {"narrative": str, "visual_prompt": str, "caregiver_context": [str, ...]}
    No "choices" field — all guidance is in caregiver_context (display-only, for caregiver's reference).
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
        "visual_prompt": "",  # Don't auto-generate; let caregiver ask
        "caregiver_context": _default_caregiver_context(fallback_narrative),
    }


def _derive_visual_prompt(user_text, narrative):
    """Build a concrete scene descriptor when the model omits visual_prompt."""
    source = (user_text or narrative or "").strip()
    if not source:
        return ""
    # Prefer the user's own words — they contain the vivid details
    words = source.split()
    return " ".join(words[:35])


def _normalize_turn(data, conversation_history):
    """Ensure every turn has valid caregiver context. visual_prompt stays empty unless rich detail present."""
    # Only populate visual_prompt if it was explicitly returned and contains detail
    visual_prompt = (data.get("visual_prompt") or "").strip()
    data["visual_prompt"] = visual_prompt  # Keep empty if not provided
    
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


def _is_generic_support_note(note):
    markers = (
        "listen warmly", "without correcting", "open question", "how it felt",
        "how this felt", "allow pauses", "reflect back", "no need to fill",
        "gentle", "validation", "encourage", "pause", "silence",
    )
    lower = note.lower()
    return any(m in lower for m in markers)


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