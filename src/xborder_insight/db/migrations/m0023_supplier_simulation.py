def up(conn):
    conn.execute('''CREATE TABLE commerce_supplier_cases (
        id TEXT PRIMARY KEY,tenant TEXT NOT NULL,candidate_id TEXT NOT NULL REFERENCES commerce_candidates(id),
        scenario TEXT NOT NULL CHECK(scenario IN ('standard','delayed')),
        status TEXT NOT NULL CHECK(status IN ('draft','rfq_sent','quoted','sample_requested','sample_received','accepted','rejected')),
        version INTEGER NOT NULL CHECK(version>0),data_kind TEXT NOT NULL CHECK(data_kind='simulation'),created_at INTEGER NOT NULL)''')
    conn.execute('''CREATE TABLE commerce_supplier_events (
        case_id TEXT NOT NULL REFERENCES commerce_supplier_cases(id),version INTEGER NOT NULL,
        payload TEXT NOT NULL,created_at INTEGER NOT NULL,PRIMARY KEY(case_id,version))''')


def down(conn):
    conn.execute('DROP TABLE commerce_supplier_events')
    conn.execute('DROP TABLE commerce_supplier_cases')
