"""Test-only helper for the G4 project fixtures (docs/G4_SPEC.md section 9).

A project is a directory with a `root.pruv` (the compiler input) plus companion module files. Companion modules are
never standalone test roots. This module only reads tests/g4/fixtures.json; it is not a package manifest.

  load()                    the parsed fixtures.json
  frontend() / rejects() / proof()    [{"name", "root" (repo-relative, `/`), ...}] in inventory order
  all_roots()               repo-relative roots of every listed project (frontend, reject, proof, runtime)
  runtime()                 the runtime projects (tests/runtime/g4_*/: root.pruv, modules, main.rs, spec.json)
  example_roots()           roots of the project examples examples/g4_*/root.pruv (not in fixtures.json)
  is_companion(rel)         True for a .pruv below a project directory that is not that project's root
  project_dir(root_rel)     absolute project directory of a repo-relative root
  project_tree(root_rel)    sorted relative file names (`/` separators) of the whole project directory
  copy_project(root, dest)  copy the project tree to the new directory `dest` (relative tree and root basename
                            preserved) -> absolute path of the copied root file
"""
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
FIXTURES = os.path.join(HERE, "fixtures.json")
GROUPS = ("frontend", "reject", "proof", "runtime")


def load():
    with open(FIXTURES, encoding="utf-8") as fh:
        return json.load(fh)


def _entries(group):
    return list(load().get(group, []))


def frontend():
    return _entries("frontend")


def rejects():
    return _entries("reject")


def proof():
    return _entries("proof")


def all_entries():
    out = []
    for g in GROUPS:
        for e in _entries(g):
            out.append(dict(e, group=g))
    return out


def all_roots():
    return [e["root"] for e in all_entries()]


def project_dir(root_rel):
    return os.path.dirname(os.path.join(ROOT, *root_rel.split("/")))


def is_companion(rel):
    """rel: repo-relative path of a .pruv file"""
    rel = rel.replace(os.sep, "/")
    roots = set(all_roots())
    if rel in roots:
        return False
    for r in roots:
        d = r.rsplit("/", 1)[0] + "/"
        if rel.startswith(d):
            return True
    # directories that hold G4 projects: a .pruv inside them that is not a listed root is a companion
    if rel.startswith("tests/g4/") and rel.endswith(".pruv"):
        return True
    parts = rel.split("/")
    if len(parts) >= 3 and parts[0] == "examples" and parts[1].startswith("g4_"):   # G4 A2 project examples
        return rel != "examples/%s/root.pruv" % parts[1]
    return len(parts) >= 4 and parts[:2] == ["tests", "must_reject"] and parts[2].startswith("g4_")


def example_roots():
    """repo-relative roots of the G4 project examples (examples/g4_*/root.pruv); not listed in fixtures.json"""
    out = []
    for name in sorted(os.listdir(os.path.join(ROOT, "examples"))):
        p = os.path.join(ROOT, "examples", name, "root.pruv")
        if name.startswith("g4_") and os.path.isfile(p):
            out.append("examples/%s/root.pruv" % name)
    return out


def runtime():
    return _entries("runtime")


def project_tree(root_rel):
    base = project_dir(root_rel)
    out = []
    for dp, dns, fns in os.walk(base):
        dns.sort()
        for fn in sorted(fns):
            out.append(os.path.relpath(os.path.join(dp, fn), base).replace(os.sep, "/"))
    return sorted(out)


def copy_project(root_abs, dest):
    """copy the directory of root_abs (the whole tree) to the new directory dest; returns the copied root path"""
    src_dir = os.path.dirname(os.path.abspath(root_abs))
    shutil.copytree(src_dir, dest)
    return os.path.join(dest, os.path.basename(root_abs))


def expected(root_rel):
    """expected diagnostic {"stage", "code"} of a rejection project (from the inventory)"""
    for e in rejects():
        if e["root"] == root_rel:
            return {"stage": e["stage"], "code": e["code"]}
    return None
