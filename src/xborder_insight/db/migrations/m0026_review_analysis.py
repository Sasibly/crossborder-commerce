"""Persist bounded review-analysis trials independently from simulated trading."""


def up(conn):
    conn.execute('''CREATE TABLE commerce_review_budgets (
        id TEXT PRIMARY KEY,tenant TEXT NOT NULL,input_fingerprint TEXT NOT NULL,
        review_limit INTEGER NOT NULL CHECK(review_limit=10),
        request_limit INTEGER NOT NULL CHECK(request_limit=20),
        requests_used INTEGER NOT NULL DEFAULT 0 CHECK(requests_used BETWEEN 0 AND 20))''')
    conn.execute('''CREATE TABLE commerce_review_analyses (
        id TEXT PRIMARY KEY,tenant TEXT NOT NULL,request_key TEXT NOT NULL,fingerprint TEXT NOT NULL,
        dataset TEXT NOT NULL,mode TEXT NOT NULL CHECK(mode IN ('baseline','live')),
        status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','partial','failed')),
        payload TEXT NOT NULL,provenance TEXT NOT NULL,result TEXT,error_code TEXT,
        request_count INTEGER NOT NULL DEFAULT 0,created_at INTEGER NOT NULL,finished_at INTEGER,
        UNIQUE(tenant,request_key))''')
    conn.execute('CREATE INDEX commerce_review_analysis_queue ON commerce_review_analyses(status,created_at)')
    conn.execute('''CREATE TRIGGER review_analysis_final_no_update BEFORE UPDATE ON commerce_review_analyses
        WHEN OLD.status IN ('succeeded','partial','failed') BEGIN SELECT RAISE(ABORT,'analysis result is immutable'); END''')
    conn.execute("CREATE TRIGGER review_analysis_no_delete BEFORE DELETE ON commerce_review_analyses BEGIN SELECT RAISE(ABORT,'analysis history is immutable'); END")
    conn.execute('''CREATE TRIGGER review_budget_monotone BEFORE UPDATE ON commerce_review_budgets
        WHEN NEW.requests_used<OLD.requests_used OR NEW.id!=OLD.id OR NEW.tenant!=OLD.tenant
        OR NEW.input_fingerprint!=OLD.input_fingerprint OR NEW.request_limit!=OLD.request_limit
        OR NEW.review_limit!=OLD.review_limit BEGIN SELECT RAISE(ABORT,'trial authorization cannot be reset'); END''')
    conn.execute("CREATE TRIGGER review_budget_no_delete BEFORE DELETE ON commerce_review_budgets BEGIN SELECT RAISE(ABORT,'trial budget cannot be deleted'); END")


def down(conn):
    if conn.execute('SELECT 1 FROM commerce_review_analyses LIMIT 1').fetchone() or conn.execute('SELECT 1 FROM commerce_review_budgets LIMIT 1').fetchone():
        raise ValueError('已有分析任务或真实调用预算，不能降级丢失结果和授权用量')
    conn.execute('DROP TABLE commerce_review_analyses')
    conn.execute('DROP TABLE commerce_review_budgets')
