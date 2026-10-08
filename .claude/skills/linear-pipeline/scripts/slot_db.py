#!/usr/bin/env python3
"""Per-slot local databases for the linear-pipeline (ADR-0014). Postgres adapter.

Each pipeline slot owns one local Postgres database, cloned from a template, so that
concurrent slots never migrate or truncate each other's tables. This is optional: it is used only
when `.agent/config.json` has a `database` block. Another engine needs its own adapter with the
same commands.

Usage (from the repo root):
  slot_db.py url <n>        print slot n's database URL
  slot_db.py name <n>       print slot n's database name
  slot_db.py ping <n>       exit 0 if the database server answers (the slot database need not exist)
  slot_db.py reset <n>      drop slot n's database and each sibling (database.siblingSuffixes),
                            and recreate them all from the template
  slot_db.py template       rebuild the template from the base database (pg_dump | pg_restore)
  slot_db.py list           show the template and every slot database that exists

Configuration comes from the `database` block of .agent/config.json (see config.md):
  baseUrlEnv               env var holding the operator's LOCAL database URL (default DB_URL)
  baseDatabase             required; the migrated local database the template is cloned from
  slotTemplate             default <baseDatabase>_template
  slotPrefix               default <baseDatabase>_s; slot n is <slotPrefix><n>
  siblingSuffixes          default []; e.g. ["_test"] when the test harness derives <db>_test
  migrationsHighWaterSql   optional query reported after a template rebuild

Only localhost URLs are accepted; the script refuses anything else.
Needs psql, pg_dump and pg_restore on PATH, and Postgres 13+ (DROP DATABASE ... WITH (FORCE)).

Exit codes: 0 ok, 2 bad usage or config, 3 base URL missing or not local, 4 database command failed.
"""

import json
import os
import re
import subprocess
import sys
import urllib.parse

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
SUFFIX_RE = re.compile(r"^[a-z0-9_]+$")


def fail(code, message):
    print(f"slot_db: {message}", file=sys.stderr)
    sys.exit(code)


def load_config():
    try:
        with open(os.path.join(".agent", "config.json"), encoding="utf-8") as f:
            block = json.load(f).get("database")
    except FileNotFoundError:
        fail(2, ".agent/config.json not found; run from the repo root")
    if not isinstance(block, dict):
        fail(2, "no `database` block in .agent/config.json; slot databases are not configured")
    base = block.get("baseDatabase")
    if not base:
        fail(2, "database.baseDatabase is required")
    cfg = {
        "baseUrlEnv": block.get("baseUrlEnv") or "DB_URL",
        "baseDatabase": base,
        "slotTemplate": block.get("slotTemplate") or f"{base}_template",
        "slotPrefix": block.get("slotPrefix") or f"{base}_s",
        "siblingSuffixes": block.get("siblingSuffixes") or [],
        "migrationsHighWaterSql": block.get("migrationsHighWaterSql"),
    }
    for key in ("baseDatabase", "slotTemplate", "slotPrefix"):
        if not NAME_RE.match(cfg[key].rstrip("_") or "x"):
            fail(2, f"database.{key} is not a plain lowercase identifier: {cfg[key]!r}")
    for suffix in cfg["siblingSuffixes"]:
        if not SUFFIX_RE.match(suffix):
            fail(2, f"database.siblingSuffixes entry is not a plain identifier suffix: {suffix!r}")
    return cfg


def base_url(cfg):
    url = os.environ.get(cfg["baseUrlEnv"], "")
    if not url:
        fail(3, f"${cfg['baseUrlEnv']} is not set")
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname not in LOCAL_HOSTS:
        fail(3, f"refusing non-local database host {parsed.hostname!r}")
    return parsed


def url_for(parsed, dbname):
    return urllib.parse.urlunparse(parsed._replace(path="/" + dbname))


def env():
    # libpq prefers PGHOST/PGPORT over the URL's host and port, and some dev environments (devenv,
    # nix shells, direnv setups) export them. Drop them so the URL alone decides the server.
    e = dict(os.environ)
    e.pop("PGPORT", None)
    e.pop("PGHOST", None)
    return e


def psql(parsed, sql, dbname="postgres", fatal=True):
    r = subprocess.run(
        ["psql", url_for(parsed, dbname), "-X", "-v", "ON_ERROR_STOP=1", "-Atc", sql],
        capture_output=True,
        text=True,
        env=env(),
    )
    if r.returncode:
        if not fatal:
            return None
        fail(4, r.stderr.strip() or f"psql exited {r.returncode}")
    return r.stdout.strip()


def slot_name(cfg, n):
    if not n.isdigit() or int(n) < 1:
        fail(2, f"slot must be a positive integer, got {n!r}")
    return f"{cfg['slotPrefix']}{int(n)}"


def exists(parsed, dbname):
    return psql(parsed, f"SELECT 1 FROM pg_database WHERE datname = '{dbname}'") == "1"


def cmd_url(cfg, parsed, n):
    print(url_for(parsed, slot_name(cfg, n)))


def cmd_name(cfg, parsed, n):
    print(slot_name(cfg, n))


def cmd_ping(cfg, parsed, n):
    slot_name(cfg, n)  # validates n
    if psql(parsed, "SELECT 1", fatal=False) != "1":
        fail(4, "database server did not answer; is the local server running?")
    print("PONG")


def cmd_reset(cfg, parsed, n):
    name = slot_name(cfg, n)
    tmpl = cfg["slotTemplate"]
    if not exists(parsed, tmpl):
        fail(4, f"template {tmpl} does not exist; run `slot_db.py template` first")
    dbs = [name] + [name + s for s in cfg["siblingSuffixes"]]
    for db in dbs:
        psql(parsed, f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')
        psql(parsed, f'CREATE DATABASE "{db}" TEMPLATE "{tmpl}"')
    print(f"RESET {', '.join(dbs)} from {tmpl}")


def cmd_template(cfg, parsed):
    base, tmpl = cfg["baseDatabase"], cfg["slotTemplate"]
    if base == tmpl:
        fail(2, "baseDatabase and slotTemplate must differ")
    if not exists(parsed, base):
        fail(4, f"base database {base} does not exist")
    psql(parsed, f'DROP DATABASE IF EXISTS "{tmpl}" WITH (FORCE)')
    psql(parsed, f'CREATE DATABASE "{tmpl}" TEMPLATE template0')
    # pg_dump works while the operator's app holds connections to the base database,
    # which CREATE DATABASE ... TEMPLATE <base> would refuse.
    dump = subprocess.Popen(
        ["pg_dump", "-Fc", "--no-owner", "--no-acl", url_for(parsed, base)],
        stdout=subprocess.PIPE,
        env=env(),
    )
    restore = subprocess.run(
        ["pg_restore", "--no-owner", "--no-acl", "--exit-on-error", "-d", url_for(parsed, tmpl)],
        stdin=dump.stdout,
        capture_output=True,
        text=True,
        env=env(),
    )
    dump.stdout.close()
    if dump.wait() or restore.returncode:
        fail(4, restore.stderr.strip() or "pg_dump or pg_restore failed")
    hwm = "not configured"
    if cfg["migrationsHighWaterSql"]:
        # Reporting only: a query that fails here must never turn a successful rebuild into a failure.
        hwm = psql(parsed, cfg["migrationsHighWaterSql"], tmpl, fatal=False) or "unknown"
    print(f"TEMPLATE {tmpl} rebuilt from {base} (migration high-water mark: {hwm})")


def cmd_list(cfg, parsed):
    prefix = cfg["slotPrefix"].replace("_", r"\_")  # `_` is a LIKE wildcard
    rows = psql(
        parsed,
        "SELECT datname FROM pg_database WHERE datname = '%s' OR datname LIKE '%s%%' ORDER BY 1"
        % (cfg["slotTemplate"], prefix),
    )
    print(rows or "(none)")


def main(argv):
    commands = ("url", "name", "ping", "reset", "template", "list")
    if not argv or argv[0] not in commands:
        fail(2, "usage: slot_db.py url|name|ping|reset <n> | template | list")
    cfg = load_config()
    parsed = base_url(cfg)
    cmd = argv[0]
    if cmd in ("url", "name", "ping", "reset"):
        if len(argv) != 2:
            fail(2, f"usage: slot_db.py {cmd} <n>")
        {"url": cmd_url, "name": cmd_name, "ping": cmd_ping, "reset": cmd_reset}[cmd](cfg, parsed, argv[1])
    elif cmd == "template":
        cmd_template(cfg, parsed)
    else:
        cmd_list(cfg, parsed)


if __name__ == "__main__":
    main(sys.argv[1:])
