"""
Applier for cerebro_training_schema.sql.

Statement-by-statement (no SQL parser issues). Idempotent.
Also seeds cerebro_skills_versions with current YAML snapshots
the first time it runs.

Run:
    railway ssh --service shift-cerebro -- /opt/venv/bin/python apply_training_schema.py
"""
import hashlib
import os
import sys

import pymysql
import yaml

DB = dict(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DATABASE", "railway"),
    port=int(os.getenv("MYSQL_PORT", "3306")),
    charset="utf8mb4",
    autocommit=False,
    connect_timeout=15,
)

SKILLS_DIR = os.path.join(os.path.dirname(__file__), "agents", "skills")


def step(label, fn):
    print(f"[ {label:<60} ]", end=" ", flush=True)
    try:
        fn()
        print("OK")
        return True
    except Exception as e:
        print(f"FAIL: {str(e)[:160]}")
        return False


def main():
    print(f"[TRAINING] connect {DB['host']}:{DB['port']}/{DB['database']}")
    conn = pymysql.connect(**DB)
    c = conn.cursor()

    # ───────── (1) cerebro_skills_versions
    def s_versions():
        c.execute("""
            CREATE TABLE IF NOT EXISTS cerebro_skills_versions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                agent_id VARCHAR(50) NOT NULL,
                version VARCHAR(40) NOT NULL,
                skill_prompt_hash CHAR(64) NOT NULL,
                skill_prompt MEDIUMTEXT NOT NULL,
                role VARCHAR(120),
                pod INT,
                pod_name VARCHAR(80),
                keywords JSON,
                captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uk_agent_hash (agent_id, skill_prompt_hash),
                INDEX idx_agent_version (agent_id, version),
                INDEX idx_captured (captured_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

    # ───────── (2) cerebro_training_pairs
    def s_training():
        c.execute("""
            CREATE TABLE IF NOT EXISTS cerebro_training_pairs (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                insight_id BIGINT NULL,
                message_id VARCHAR(120) NOT NULL UNIQUE,
                app_id VARCHAR(32) NOT NULL,
                tenant_id VARCHAR(50) NOT NULL,
                agent_id VARCHAR(50) NOT NULL,
                skill_version_id INT NULL,
                system_prompt MEDIUMTEXT NOT NULL,
                user_message TEXT NOT NULL,
                user_message_scrubbed TEXT NULL,
                assistant_response MEDIUMTEXT NOT NULL,
                reasoning_trace JSON NULL,
                upstream_model VARCHAR(80) NULL,
                quality_label ENUM(
                    'unverified','liked','disliked','approved','rejected','corrected'
                ) NOT NULL DEFAULT 'unverified',
                human_correction MEDIUMTEXT NULL,
                like_count INT NOT NULL DEFAULT 0,
                dislike_count INT NOT NULL DEFAULT 0,
                avg_rating DECIMAL(3,2) NULL,
                feedback_count INT NOT NULL DEFAULT 0,
                legal_status ENUM('unrestricted','tos_restricted','consented')
                    NOT NULL DEFAULT 'unrestricted',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_app (app_id),
                INDEX idx_tenant (tenant_id),
                INDEX idx_agent (agent_id),
                INDEX idx_quality (quality_label),
                INDEX idx_app_quality (app_id, quality_label),
                INDEX idx_legal (legal_status),
                INDEX idx_insight (insight_id),
                INDEX idx_skill_version (skill_version_id),
                INDEX idx_created (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

    # ───────── (3) cerebro_feedback_events
    def s_feedback():
        c.execute("""
            CREATE TABLE IF NOT EXISTS cerebro_feedback_events (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                message_id VARCHAR(120) NULL,
                session_id VARCHAR(120) NOT NULL,
                app_id VARCHAR(32) NOT NULL,
                tenant_id VARCHAR(50) NOT NULL,
                user_id VARCHAR(120) NULL,
                user_anonymous BOOLEAN NOT NULL DEFAULT FALSE,
                feedback_type ENUM(
                    'like','dislike','chip','free_text','session_nps','star_rating'
                ) NOT NULL,
                rating_value SMALLINT NULL,
                chip_key VARCHAR(60) NULL,
                free_text TEXT NULL,
                upstream_model VARCHAR(80) NULL,
                agent_id VARCHAR(50) NULL,
                user_agent VARCHAR(255) NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_message (message_id),
                INDEX idx_session (session_id),
                INDEX idx_app (app_id),
                INDEX idx_user (user_id),
                INDEX idx_type (feedback_type),
                INDEX idx_created (created_at),
                INDEX idx_app_type (app_id, feedback_type)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

    # ───────── (4) view
    def s_view():
        c.execute("""
            CREATE OR REPLACE VIEW v_training_pairs_with_feedback AS
            SELECT
                tp.id,
                tp.message_id,
                tp.app_id,
                tp.tenant_id,
                tp.agent_id,
                tp.quality_label,
                tp.upstream_model,
                tp.legal_status,
                tp.created_at,
                COALESCE((SELECT COUNT(*) FROM cerebro_feedback_events fe
                          WHERE fe.message_id = tp.message_id AND fe.feedback_type='like'), 0) AS likes,
                COALESCE((SELECT COUNT(*) FROM cerebro_feedback_events fe
                          WHERE fe.message_id = tp.message_id AND fe.feedback_type='dislike'), 0) AS dislikes,
                (SELECT GROUP_CONCAT(DISTINCT chip_key)
                 FROM cerebro_feedback_events fe
                 WHERE fe.message_id = tp.message_id AND fe.feedback_type='chip') AS chip_reasons
            FROM cerebro_training_pairs tp
        """)

    # ───────── (5) seed cerebro_skills_versions con YAMLs actuales
    def s_seed_skills():
        if not os.path.isdir(SKILLS_DIR):
            print(f"\n     skills dir not found: {SKILLS_DIR}")
            return
        seeded = 0
        for filename in sorted(os.listdir(SKILLS_DIR)):
            if not filename.endswith(".yaml"):
                continue
            agent_id = filename.replace(".yaml", "")
            try:
                with open(os.path.join(SKILLS_DIR, filename), "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                skill_prompt = data.get("skill_prompt", "") or ""
                version = str(data.get("version", "1.0.0"))
                role = data.get("role", "")
                pod = data.get("pod")
                pod_name = data.get("pod_name", "")
                keywords = data.get("keywords", [])
                import json
                kw_json = json.dumps(keywords)
                h = hashlib.sha256(skill_prompt.encode("utf-8")).hexdigest()

                # ON DUPLICATE KEY: si ya existe (mismo agent+hash), no-op
                c.execute(
                    """
                    INSERT INTO cerebro_skills_versions
                    (agent_id, version, skill_prompt_hash, skill_prompt,
                     role, pod, pod_name, keywords)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE captured_at = captured_at
                    """,
                    (agent_id, version, h, skill_prompt, role, pod, pod_name, kw_json),
                )
                if c.rowcount > 0:
                    seeded += 1
            except Exception as e:
                print(f"\n     skip {agent_id}: {e}")
        print(f" (snapshots seeded: {seeded})", end="")

    steps = [
        ("cerebro_skills_versions table",   s_versions),
        ("cerebro_training_pairs table",    s_training),
        ("cerebro_feedback_events table",   s_feedback),
        ("v_training_pairs_with_feedback",  s_view),
        ("seed cerebro_skills_versions",    s_seed_skills),
    ]

    ok = fail = 0
    for label, fn in steps:
        if step(label, fn):
            ok += 1
        else:
            fail += 1

    conn.commit()

    # Verify
    print()
    for t in ("cerebro_skills_versions", "cerebro_training_pairs", "cerebro_feedback_events"):
        c.execute(f"SELECT COUNT(*) FROM {t}")
        cnt = c.fetchone()[0]
        print(f"  {t}: {cnt} rows")

    c.execute(
        "SELECT agent_id, COUNT(*) FROM cerebro_skills_versions "
        "GROUP BY agent_id ORDER BY agent_id"
    )
    rows = c.fetchall()
    print(f"  skills snapshotted: {len(rows)} agents → {dict(rows)}")

    conn.close()
    print(f"\n[TRAINING] DONE — ok={ok} fail={fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
