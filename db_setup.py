import sqlite3
import os
from datetime import datetime
import uuid
import json


DB_PATH = os.path.join(os.path.dirname(__file__), "data", "rt_therapy.db")


## Function to create connection to the SQLite database

def create_connection():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row  # This allows us to access columns by name
        ## For foreign key constraints to work in SQLite, we need to enable it for each connection
        conn.execute("PRAGMA foreign_keys = ON") ## Doesn't allow us to have orphan records in child tables that don't have a corresponding record in the parent table.
    except sqlite3.Error as e:
        print(f"Could not connect to SQLite DB. The error '{e}' occurred")
    return conn
    
## As for the Database schema, following tables are currently needed:
'''
Tabs: for keeping track of different stories for a user. Like different memory recalls extended to stories.
      Keeps track of titles, themes, timestamps etc.
      Each tabs will have multiple chats associated with it.

Messages: Holds the actual messages or dialogies for each story or tab. 
        Each message will have a role (user or assistant), content, and timestamp.

Visual_Triggers: keeps track of images generated during the recall session. Like for some particular bit of a story if there
                is a visual trigger, we can store the image details here. This can be used to create a more immersive experience during recall sessions.
                Each visual trigger will be associated with a particular message in the Messages table, so we can know exactly which part of the story it corresponds to.
'''

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True) ## Ensure that the directory for the database exists
    with create_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tabs (
                id             TEXT PRIMARY KEY,
                title          TEXT NOT NULL,
                theme_keywords TEXT,
                created_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL,
                sealed         INTEGER NOT NULL DEFAULT 0,
                depth_level    INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS messages (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                tab_id             TEXT NOT NULL REFERENCES tabs(id) ON DELETE CASCADE,
                parent_message_id  INTEGER REFERENCES messages(id) ON DELETE CASCADE,
                role               TEXT NOT NULL CHECK(role IN ('user','assistant')),
                content            TEXT NOT NULL,
                choices_offered    TEXT,
                fact_context       TEXT,
                caregiver_notes    TEXT,
                timestamp          TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS visual_triggers (
                id                   TEXT PRIMARY KEY,
                tab_id               TEXT NOT NULL REFERENCES tabs(id) ON DELETE CASCADE,
                source_message_id    INTEGER REFERENCES messages(id) ON DELETE CASCADE,
                llm_generated_prompt TEXT NOT NULL,
                edited_prompt        TEXT,
                image_filename       TEXT,
                version              INTEGER NOT NULL DEFAULT 1,
                approved             INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_messages_tab ON messages(tab_id);
            CREATE INDEX IF NOT EXISTS idx_visuals_tab ON visual_triggers(tab_id);
        """)
    _migrate_schema()


def _column_exists(conn, table, column):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def _migrate_schema():
    """Safely add columns introduced after initial release — safe to run repeatedly."""
    with create_connection() as conn:
        if not _column_exists(conn, "messages", "fact_context"):
            conn.execute("ALTER TABLE messages ADD COLUMN fact_context TEXT")
        if not _column_exists(conn, "messages", "parent_message_id"):
            conn.execute(
                "ALTER TABLE messages ADD COLUMN parent_message_id INTEGER "
                "REFERENCES messages(id) ON DELETE CASCADE"
            )
        if not _column_exists(conn, "messages", "caregiver_notes"):
            conn.execute("ALTER TABLE messages ADD COLUMN caregiver_notes TEXT")
        if not _column_exists(conn, "tabs", "sealed_story"):
            conn.execute("ALTER TABLE tabs ADD COLUMN sealed_story TEXT")
        if not _column_exists(conn, "tabs", "game_data"):
            conn.execute("ALTER TABLE tabs ADD COLUMN game_data TEXT")
        conn.commit()
    _backfill_message_parents()


def _backfill_message_parents():
    """Link legacy linear messages into a single chain per tab (one-time, idempotent)."""
    with create_connection() as conn:
        tabs = conn.execute("SELECT id FROM tabs").fetchall()
        for tab in tabs:
            tab_id = tab["id"]
            rows = conn.execute(
                "SELECT id, parent_message_id FROM messages WHERE tab_id=? ORDER BY id ASC",
                (tab_id,),
            ).fetchall()
            prev_id = None
            for row in rows:
                if row["parent_message_id"] is None and prev_id is not None:
                    conn.execute(
                        "UPDATE messages SET parent_message_id=? WHERE id=?",
                        (prev_id, row["id"]),
                    )
                prev_id = row["id"]
        conn.commit()


def current_timestamp():
    return datetime.utcnow().isoformat() + "Z" ## ISO format with UTC timezone

def touch_tab(tab_id):
    with create_connection() as conn:
        conn.execute(
            "UPDATE tabs SET updated_at=? WHERE id=?",
            (current_timestamp(), tab_id)
        )

def save_sealed_story(tab_id, story_data):
    """Save structured or text first-person story for a sealed tab."""
    story_json = json.dumps(story_data) if isinstance(story_data, (list, dict)) else str(story_data)
    with create_connection() as conn:
        conn.execute(
            "UPDATE tabs SET sealed_story=?, updated_at=? WHERE id=?",
            (story_json, current_timestamp(), tab_id)
        )

def get_sealed_story(tab_id):
    """Retrieve saved first-person story for a tab if available."""
    with create_connection() as conn:
        row = conn.execute("SELECT sealed_story FROM tabs WHERE id=?", (tab_id,)).fetchone()
    if not row or not row["sealed_story"]:
        return None
    try:
        return json.loads(row["sealed_story"])
    except (json.JSONDecodeError, TypeError):
        return row["sealed_story"]

def save_game_data(tab_id, game_data):
    """Save memory game questions for a tab."""
    game_json = json.dumps(game_data) if isinstance(game_data, (list, dict)) else str(game_data)
    with create_connection() as conn:
        conn.execute(
            "UPDATE tabs SET game_data=?, updated_at=? WHERE id=?",
            (game_json, current_timestamp(), tab_id)
        )

def get_game_data(tab_id):
    """Retrieve saved memory game questions for a tab."""
    with create_connection() as conn:
        row = conn.execute("SELECT game_data FROM tabs WHERE id=?", (tab_id,)).fetchone()
    if not row or not row["game_data"]:
        return None
    try:
        return json.loads(row["game_data"])
    except (json.JSONDecodeError, TypeError):
        return None


def list_tabs():
    with create_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM tabs ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]

def get_tab(tab_id):
    with create_connection() as conn:
        row = conn.execute("SELECT * FROM tabs WHERE id=?", (tab_id,)).fetchone()
    return dict(row) if row else None

def create_tab(title, theme_keywords=None):
    now = current_timestamp()
    tab_id = str(uuid.uuid4())
    with create_connection() as conn:
        conn.execute(
            "INSERT INTO tabs (id, title, theme_keywords, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (tab_id, title, theme_keywords, now, now)
        )

    return tab_id

def increment_depth(tab_id):
    with create_connection() as conn:
        conn.execute(
            "UPDATE tabs SET depth_level = depth_level + 1, updated_at=? WHERE id=?",
            (current_timestamp(), tab_id)
        )

def decrement_depth(tab_id):
    with create_connection() as conn:
        conn.execute(
            "UPDATE tabs SET depth_level = MAX(0, depth_level - 1), updated_at=? WHERE id=?",
            (current_timestamp(), tab_id)
        )

def seal_tab(tab_id):
    with create_connection() as conn:
        conn.execute(
            "UPDATE tabs SET sealed=1, updated_at=? WHERE id=?",
            (current_timestamp(), tab_id)
        )

def update_tab_title(tab_id, title):
    title = (title or "").strip()
    if not title:
        return False
    with create_connection() as conn:
        conn.execute(
            "UPDATE tabs SET title=?, updated_at=? WHERE id=?",
            (title, current_timestamp(), tab_id)
        )
    return True

def add_message(tab_id, role, content, choices=None, parent_message_id=None, caregiver_notes=None):
    choices_json = json.dumps(choices) if choices else None
    notes_json = json.dumps(caregiver_notes) if caregiver_notes else None
    with create_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO messages
               (tab_id, parent_message_id, role, content, choices_offered, caregiver_notes, timestamp)
               VALUES (?,?,?,?,?,?,?)""",
            (tab_id, parent_message_id, role, content, choices_json, notes_json, current_timestamp())
        )
        msg_id = cursor.lastrowid
    touch_tab(tab_id)
    return msg_id

def update_message_fact(msg_id, fact_dict):
    """Store fact-grounding context JSON on an existing assistant message."""
    fact_json = json.dumps(fact_dict)
    with create_connection() as conn:
        conn.execute(
            "UPDATE messages SET fact_context=? WHERE id=?",
            (fact_json, msg_id)
        )

def update_message_caregiver_notes(msg_id, notes):
    """Store LLM-generated caregiver context on an assistant message."""
    notes_json = json.dumps(notes) if notes else None
    with create_connection() as conn:
        conn.execute(
            "UPDATE messages SET caregiver_notes=? WHERE id=?",
            (notes_json, msg_id)
        )

def get_message(message_id):
    with create_connection() as conn:
        row = conn.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
    if not row:
        return None
    return _deserialize_message(dict(row))

def _deserialize_message(d):
    d["choices_offered"] = json.loads(d["choices_offered"]) if d.get("choices_offered") else []
    d["fact_context"] = json.loads(d["fact_context"]) if d.get("fact_context") else None
    if d.get("caregiver_notes"):
        try:
            d["caregiver_notes"] = json.loads(d["caregiver_notes"])
        except (json.JSONDecodeError, TypeError):
            d["caregiver_notes"] = [d["caregiver_notes"]]
    else:
        d["caregiver_notes"] = None
    return d

def get_messages(tab_id):
    with create_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE tab_id=? ORDER BY id ASC", (tab_id,)
        ).fetchall()
    return [_deserialize_message(dict(r)) for r in rows]

def get_active_leaf_id(tab_id):
    """Return the id of the most recently added message in a tab (deepest active tip)."""
    with create_connection() as conn:
        row = conn.execute(
            "SELECT id FROM messages WHERE tab_id=? ORDER BY id DESC LIMIT 1",
            (tab_id,)
        ).fetchone()
    return row["id"] if row else None

def get_message_branch(tab_id, message_id=None):
    """
    Fetch the active path from root ancestor down to the target node.
    If message_id is omitted, uses the latest leaf in the tab.
    """
    if message_id is None:
        message_id = get_active_leaf_id(tab_id)
    if message_id is None:
        return []

    chain = []
    current_id = message_id
    seen = set()
    with create_connection() as conn:
        while current_id is not None:
            if current_id in seen:
                break
            seen.add(current_id)
            row = conn.execute(
                "SELECT * FROM messages WHERE id=? AND tab_id=?",
                (current_id, tab_id)
            ).fetchone()
            if not row:
                break
            chain.append(_deserialize_message(dict(row)))
            current_id = row["parent_message_id"]

    chain.reverse()
    return chain

def get_children(message_id):
    with create_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE parent_message_id=? ORDER BY id ASC",
            (message_id,),
        ).fetchall()
    return [_deserialize_message(dict(r)) for r in rows]

def get_deepest_leaf(message_id):
    """Follow the most recent child chain to the tip of a sub-branch."""
    current = message_id
    while True:
        children = get_children(current)
        if not children:
            return current
        current = children[-1]["id"]

def build_branch_context(tab_id, active_at=None):
    """
    Build UI metadata for the active path: turn numbers, fork points, alternates.
    """
    all_msgs = get_messages(tab_id)
    if not all_msgs:
        return {"trail": [], "annotations": {}, "turn_count": 0}

    children_map = {}
    for m in all_msgs:
        pid = m.get("parent_message_id")
        if pid:
            children_map.setdefault(pid, []).append(m)

    branch = get_message_branch(tab_id, active_at)
    active_ids = {m["id"] for m in branch}
    annotations = {}
    trail = []
    turn_num = 0

    for msg in branch:
        meta = {
            "turn": None,
            "is_fork_point": False,
            "fork_count": 0,
            "is_branch_child": False,
            "branch_label": None,
            "fork_from_id": None,
            "alternates": [],
        }

        if msg["role"] == "user":
            turn_num += 1
            meta["turn"] = turn_num
            pid = msg.get("parent_message_id")
            if pid:
                siblings = [c for c in children_map.get(pid, []) if c["role"] == "user"]
                if len(siblings) > 1:
                    idx = next(i for i, s in enumerate(siblings) if s["id"] == msg["id"])
                    meta["is_branch_child"] = True
                    meta["branch_label"] = chr(65 + idx)
                    meta["fork_from_id"] = pid
                    for s in siblings:
                        if s["id"] != msg["id"]:
                            meta["alternates"].append({
                                "preview": s["content"][:55],
                                "at": get_deepest_leaf(s["id"]),
                                "label": chr(65 + siblings.index(s)),
                            })

        if msg["role"] == "assistant":
            user_children = [c for c in children_map.get(msg["id"], []) if c["role"] == "user"]
            if len(user_children) > 1:
                meta["is_fork_point"] = True
                meta["fork_count"] = len(user_children)
                for uc in user_children:
                    if uc["id"] not in active_ids:
                        meta["alternates"].append({
                            "preview": uc["content"][:55],
                            "at": get_deepest_leaf(uc["id"]),
                            "label": chr(65 + user_children.index(uc)),
                        })

        annotations[msg["id"]] = meta
        trail.append({"msg_id": msg["id"], "role": msg["role"], **meta})

    return {
        "trail": trail,
        "annotations": annotations,
        "turn_count": turn_num,
    }

def delete_message_node(message_id):
    """
    Delete a message node; ON DELETE CASCADE removes all descendant sub-branches.
    Returns the tab_id of the deleted message, or None if not found.
    """
    msg = get_message(message_id)
    if not msg:
        return None
    tab_id = msg["tab_id"]
    subtree_ids = _collect_subtree_ids(message_id)
    placeholders = ",".join("?" * len(subtree_ids))
    with create_connection() as conn:
        conn.execute(
            f"DELETE FROM visual_triggers WHERE source_message_id IN ({placeholders})",
            subtree_ids,
        )
        conn.execute("DELETE FROM messages WHERE id=?", (message_id,))
        conn.commit()
    touch_tab(tab_id)
    return tab_id

def _collect_subtree_ids(message_id):
    """Return message_id and all descendant ids (breadth-first)."""
    ids = []
    queue = [message_id]
    with create_connection() as conn:
        while queue:
            current = queue.pop(0)
            ids.append(current)
            rows = conn.execute(
                "SELECT id FROM messages WHERE parent_message_id=?", (current,)
            ).fetchall()
            queue.extend(r["id"] for r in rows)
    return ids


def get_children(message_id):
    with create_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE parent_message_id=? ORDER BY id ASC",
            (message_id,),
        ).fetchall()
    return [_deserialize_message(dict(r)) for r in rows]


def get_deepest_leaf(message_id):
    """Follow the most recent child chain to the tip of a sub-branch."""
    current = message_id
    while True:
        children = get_children(current)
        if not children:
            return current
        current = children[-1]["id"]


def build_branch_context(tab_id, active_at=None):
    """
    Build branch trail metadata: fork points, path labels, and alternate routes.
    """
    all_msgs = get_messages(tab_id)
    if not all_msgs:
        return {"trail": [], "annotations": {}, "turn_count": 0, "fork_points": []}

    children_map = {}
    for m in all_msgs:
        pid = m.get("parent_message_id")
        if pid:
            children_map.setdefault(pid, []).append(m)

    branch = get_message_branch(tab_id, active_at)
    active_ids = {m["id"] for m in branch}

    trail = []
    annotations = {}
    fork_points = []
    turn_num = 0

    for msg in branch:
        meta = {
            "turn": None,
            "is_fork_point": False,
            "is_branch_child": False,
            "branch_label": None,
            "fork_from_id": None,
            "fork_count": 0,
            "alternates": [],
        }

        if msg["role"] == "user":
            turn_num += 1
            meta["turn"] = turn_num
            parent_id = msg.get("parent_message_id")
            if parent_id:
                siblings = [c for c in children_map.get(parent_id, []) if c["role"] == "user"]
                if len(siblings) > 1:
                    idx = next(i for i, s in enumerate(siblings) if s["id"] == msg["id"])
                    meta["is_branch_child"] = True
                    meta["branch_label"] = f"Path {chr(65 + idx)}"
                    meta["fork_from_id"] = parent_id
                    for s in siblings:
                        if s["id"] != msg["id"]:
                            meta["alternates"].append({
                                "preview": s["content"][:55] + ("…" if len(s["content"]) > 55 else ""),
                                "at": get_deepest_leaf(s["id"]),
                                "label": f"Path {chr(65 + siblings.index(s))}",
                            })

        if msg["role"] == "assistant":
            user_children = [c for c in children_map.get(msg["id"], []) if c["role"] == "user"]
            if len(user_children) > 1:
                meta["is_fork_point"] = True
                meta["fork_count"] = len(user_children)
                fork_points.append(msg["id"])
                active_child = next((c for c in user_children if c["id"] in active_ids), None)
                for uc in user_children:
                    if uc["id"] not in active_ids:
                        meta["alternates"].append({
                            "preview": uc["content"][:55] + ("…" if len(uc["content"]) > 55 else ""),
                            "at": get_deepest_leaf(uc["id"]),
                            "label": "Unexplored path",
                        })
                if active_child:
                    meta["active_path_preview"] = active_child["content"][:55]

        annotations[msg["id"]] = meta
        trail.append({"msg_id": msg["id"], "role": msg["role"], **meta})

    all_alternates = []
    for step in trail:
        all_alternates.extend(step.get("alternates", []))

    return {
        "trail": trail,
        "annotations": annotations,
        "turn_count": turn_num,
        "fork_points": fork_points,
        "alternates": all_alternates,
    }


def get_visuals_for_tab(tab_id):
    with create_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM visual_triggers WHERE tab_id=? ORDER BY rowid ASC", (tab_id,)
        ).fetchall()
    return [dict(r) for r in rows]


## For creating a visual trigger when the AI generates a visual prompt and we generate an image for it. 
# This is called from app.py when the AI generates a visual prompt and we generate an image for it.
def create_visual_trigger(tab_id, source_message_id, llm_prompt):
    vt_id = str(uuid.uuid4())
    with create_connection() as conn:
        conn.execute(
            """INSERT INTO visual_triggers
               (id, tab_id, source_message_id, llm_generated_prompt)
               VALUES (?,?,?,?)""",
            (vt_id, tab_id, source_message_id, llm_prompt)
        )
    return vt_id

## For updating the visual trigger after user edits the prompt and saves it. This is called from app.py when user edits the prompt and saves it.

def update_visual_trigger(vt_id, edited_prompt, image_filename, version):
    with create_connection() as conn:
        conn.execute(
            """UPDATE visual_triggers
               SET edited_prompt=?, image_filename=?, version=?
               WHERE id=?""",
            (edited_prompt, image_filename, version, vt_id)
        )

if __name__ == "__main__":
    #init_db()
    print(f"Current time is: {current_timestamp()}")
