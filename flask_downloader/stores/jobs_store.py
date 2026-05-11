import json


def read_jobs_payload(jobs_file):
    with open(jobs_file, "r", encoding="utf-8") as fh:
        return json.load(fh) or []


def write_jobs_payload(jobs_file, payload):
    with open(jobs_file, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
