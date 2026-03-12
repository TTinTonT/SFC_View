from bonepile_disposition import run_bonepile_parse_job, new_job_id, connect_db
job = new_job_id()
print("Starting job:", job)
run_bonepile_parse_job(job)
conn = connect_db()
print("Rows parsed:", conn.execute("SELECT COUNT(*) FROM bonepile_entries").fetchone()[0])
print("Sample:", conn.execute("SELECT sn, status, pic FROM bonepile_entries LIMIT 10").fetchall())
