"""G6 A2 (docs/G6_SPEC.md section 12): Rust-source boundary helpers for the standard catalog and for
`trusted rust fn` declarations, the three check modes, and the `<out>.foreign.json` manifest.

ForeignGen is owned by a codegen.Gen (only created for a program that uses G6). Helpers are private Rust functions
named
    pruv_g6_<op>__<enc>[__<enc>]      catalog instance; <enc> = typeinfo.encode of each (concrete, un-lowered) type
                                      argument, e.g. pruv_g6_vec_push__i, pruv_g6_map_insert__i__b
    pruv_g6_map_updated__<enc>__<enc> contract scan used by a requires clause (not a catalog operation)
    NAME                              the helper of `trusted rust fn NAME` (same name as the declaration)
and are emitted once each, in first-use order, in front of the Pruv functions.

Check modes (Gen.fmode): requires = requires checks in every helper; all = also ensures (snapshots are `.clone()`s
taken before the operation; the actual contents are compared afterwards); off = no contract checks.  Indexing is
checked in every mode (`vec_get`, `string_byte`).  `all` spends the contract budget: one unit per visited element
or entry, a fresh budget per helper call; exhaustion -> `pruv: foreign contract undefined: NAME: budget`.
"""
import json

from vast import *
from typeinfo import encode, format_type
from codegen import rty, cty, conv, show, rstr
from modules import safe_type     # G4: nominal identities in helper names use their [0-9A-Za-z_] encoding


def _budget_line(n):
    return "let mut pruv_budget: i64 = %s;" % format(n, "_")


class ForeignGen:
    def __init__(s, gen):
        s.g = gen
        s.mode = gen.fmode
        s.req = s.mode != "off"
        s.ens = s.mode == "all"
        s.items = {}       # helper name -> text (insertion order = first use)
        s.catalog = []     # manifest: executable catalog instances in first-use order
        s.called = set()   # trusted fn names called from an emitted function

    # ------------------------------------------------------------------ results
    def helper_texts(s):
        return list(s.items.values())

    def manifest(s, externs):
        g = s.g
        trusted = []
        for f in g.prog.functions:
            if f.foreign is None:
                continue
            # G4 A2: explicit mode lists the source-qualified identity (crate::m::f), never the encoded stem
            trusted.append({"name": getattr(f, "disp", f.name), "path": f.foreign["path"], "line": f.line, "col": f.col,
                            "effects": list(f.effects),
                            "requires": [show(r) for r in f.requires],
                            "ensures": [show(x) for x in f.ensures],
                            "reachable": f.name in s.called})
        doc = {"schema": "pruv-foreign-v1", "backend": "rust", "check_mode": s.mode, "rustc_checked": False,
               "trusted": trusted, "catalog": list(s.catalog),
               "externs": [{"name": n, "path": p} for n, p in externs]}
        return json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=False) + "\n"

    # ------------------------------------------------------------------ helper skeleton
    def _fn(s, name, params, ret, body):
        """text of `fn name(params) -> ret { guard; budget; body }`; body: lines (already without indentation)"""
        g = s.g
        L = [g.allow, "fn %s(%s)%s {" % (name, params, "" if ret is None else " -> " + ret)]
        if s.req:
            L.append("    let pruv_g = pruv_ctx(%s);" % rstr(s.op))
        if s.ens:
            L.append("    " + _budget_line(g.budget))
        L.extend("    " + x for x in body)
        L.append("}")
        return "\n".join(L) + "\n"

    def _req(s, cond, text):
        return ["if !(%s) { pruv_g6_req(%s, %s); }" % (cond, rstr(s.op), rstr(text))] if s.req else []

    def _ens(s, cond, text):
        return ["if !(%s) { pruv_g6_ens(%s, %s); }" % (cond, rstr(s.op), rstr(text))] if s.ens else []

    def _snap(s, ty, src):
        """snapshot of a consumed input (mode all): charge its elements, then an independent clone"""
        if not s.ens:
            return []
        return ["pruv_g6_charge(&mut pruv_budget, %s.len());" % src, "let pruv_snap: %s = %s.clone();" % (ty, src)]

    # ------------------------------------------------------------------ catalog
    def catalog_helper(s, op, low, src):
        if not src and low:
            src = low
        name = "pruv_g6_" + op + "".join("__" + encode(safe_type(t)) for t in src)
        if name not in s.items:
            s.op = op
            s.items[name] = s._catalog_text(op, name, low)
            s.catalog.append({"op": op, "type_args": [format_type(t) for t in src]})
        return name

    def _catalog_text(s, op, name, low):
        STRING = "::std::string::String"
        if op in ("vec_new", "vec_push", "vec_get"):
            T = rty(low[0])
            V = rty(Type("vec", (low[0],)))
        elif op in ("map_new", "map_get", "map_insert"):
            K, T = rty(low[0]), rty(low[1])
            M = rty(Type("hashmap", (low[0], low[1])))
            OPT = rty(mk_option(low[1]))
        if op == "vec_new":
            body = ["let pruv_r: %s = ::std::vec::Vec::<%s>::new();" % (V, T)]
            body += s._ens("pruv_r.len() == 0", "len(result) == 0")
            body += ["pruv_r"]
            return s._fn(name, "", V, body)
        if op == "vec_push":
            body = s._req("(v.len() as u64) < (1u64 << 40)", "len(v) < 2^40")
            body += s._snap(V, "v")
            body += ["v.push(x);"]
            body += s._ens("v.len() == pruv_snap.len() + 1", "len(result) == len(v) + 1")
            if s.ens:
                body += ["pruv_g6_charge(&mut pruv_budget, pruv_snap.len());"]
            body += s._ens("v[..pruv_snap.len()] == pruv_snap[..]", "result[..len(v)] == v")
            if s.ens:
                body += ["pruv_g6_charge(&mut pruv_budget, 1);"]   # one visited element (G6_SPEC 12.3)
            body += s._ens("v[pruv_snap.len()] == x", "result[len(v)] == x")
            body += ["v"]
            return s._fn(name, "mut v: %s, x: %s" % (V, T), V, body)
        if op == "vec_get":
            body = s._req("i >= 0 && (i as u64) < (v.len() as u64)", "0 <= i && i < len(v)")
            body += ["let pruv_k: usize = if i >= 0 && (i as u64) < (v.len() as u64) { i as usize } "
                     "else { pruv_g6_repr(\"index\") };",
                     "let pruv_r: %s = v[pruv_k];" % T]
            if s.ens:
                body += ["pruv_g6_charge(&mut pruv_budget, 1);"]   # one visited element (G6_SPEC 12.3)
            body += s._ens("v.get(pruv_k).copied() == Some(pruv_r)", "result == v[i]")
            body += ["pruv_r"]
            return s._fn(name, "v: &%s, i: i64" % V, T, body)
        if op == "map_new":
            body = ["let pruv_r: %s = ::std::collections::HashMap::<%s, %s>::new();" % (M, K, T)]
            body += s._ens("pruv_r.len() == 0", "len(result) == 0")
            body += ["pruv_r"]
            return s._fn(name, "", M, body)
        if op == "map_get":
            body = ["let pruv_r: %s = m.get(&k).copied();" % OPT]
            if s.ens:
                body += ["pruv_g6_charge(&mut pruv_budget, 1);"]   # one visited element (G6_SPEC 12.3)
            body += s._ens("m.contains_key(&k) == pruv_r.is_some() && m.get(&k).copied() == pruv_r",
                           "result == map_lookup(m, k)")
            body += ["pruv_r"]
            return s._fn(name, "m: &%s, k: %s" % (M, K), OPT, body)
        if op == "map_insert":
            body = s._req("m.contains_key(&k) || (m.len() as u64) < (1u64 << 40)", "k in m || len(m) < 2^40")
            body += s._snap(M, "m")
            body += ["let _ = m.insert(k, v);"]
            body += s._ens("m.len() == pruv_snap.len() + (if pruv_snap.contains_key(&k) { 0 } else { 1 })",
                           "len(result) == len(m) + (k absent ? 1 : 0)")
            if s.ens:
                body += ["pruv_g6_charge(&mut pruv_budget, 1);"]   # one visited element (G6_SPEC 12.3)
            body += s._ens("m.get(&k) == Some(&v)", "result[k] == v")
            if s.ens:
                body += ["for (pruv_sk, pruv_sv) in pruv_snap.iter() {",
                         "    pruv_g6_charge(&mut pruv_budget, 1);",
                         "    if *pruv_sk != k && m.get(pruv_sk) != Some(pruv_sv) { "
                         "pruv_g6_ens(%s, \"entries other than k are unchanged\"); }" % rstr(op),
                         "}"]
            body += ["m"]
            return s._fn(name, "mut m: %s, k: %s, v: %s" % (M, K, T), M, body)
        if op == "string_new":
            body = ["let pruv_r: %s = ::std::string::String::new();" % STRING]
            body += s._ens("pruv_r.len() == 0", "len(result) == 0")
            body += ["pruv_r"]
            return s._fn(name, "", STRING, body)
        if op == "string_push_str":
            body = s._req("(s.len() as u64) + (text.len() as u64) <= (1u64 << 40)", "len(s) + len(text) <= 2^40")
            body += s._snap(STRING, "s")
            body += ["s.push_str(text);"]
            body += s._ens("s.len() == pruv_snap.len() + text.len()", "len(result) == len(s) + len(text)")
            if s.ens:
                body += ["pruv_g6_charge(&mut pruv_budget, pruv_snap.len());"]
            body += s._ens("s.as_bytes()[..pruv_snap.len()] == pruv_snap.as_bytes()[..]", "result[..len(s)] == s")
            if s.ens:
                body += ["pruv_g6_charge(&mut pruv_budget, text.len());"]
            body += s._ens("s.as_bytes()[pruv_snap.len()..] == text.as_bytes()[..]",
                           "result[len(s)..] == text")
            body += ["s"]
            return s._fn(name, "mut s: %s, text: &str" % STRING, STRING, body)
        if op == "string_byte":
            body = s._req("i >= 0 && (i as u64) < (s.len() as u64)", "0 <= i && i < len(s)")
            body += ["let pruv_k: usize = if i >= 0 && (i as u64) < (s.len() as u64) { i as usize } "
                     "else { pruv_g6_repr(\"index\") };",
                     "let pruv_r: i64 = s.as_bytes()[pruv_k] as i64;"]
            if s.ens:
                body += ["pruv_g6_charge(&mut pruv_budget, 1);"]   # one visited element (G6_SPEC 12.3)
            body += s._ens("s.as_bytes().get(pruv_k).map(|pruv_b| *pruv_b as i64) == Some(pruv_r)",
                           "result == s[i]")
            body += ["pruv_r"]
            return s._fn(name, "s: &%s, i: i64" % STRING, "i64", body)
        if op == "string_to_str":
            body = []
            if s.ens:
                body += ["pruv_g6_charge(&mut pruv_budget, s.len());"]
            body += ["let pruv_r: %s = s.clone();" % STRING]
            body += s._ens("pruv_r.as_bytes() == s.as_bytes()", "bytes of result equal bytes of s")
            body += ["pruv_r"]
            return s._fn(name, "s: &%s" % STRING, STRING, body)
        raise Exception("codegen: unknown catalog operation %s" % op)

    # ------------------------------------------------------------------ contract-only scan (requires)
    def map_updated_helper(s, kt, vt, src):
        name = "pruv_g6_map_updated" + "".join("__" + encode(safe_type(t)) for t in src)
        if name in s.items:
            return name
        s.op = "map_updated"
        M = rty(Type("hashmap", (kt, vt)))
        K = rty(kt)
        keyconv = "i64::try_from(pruv_kk).ok()" if kt == I64 else "Some(pruv_kk)"
        L = [s.g.allow,
             "fn %s(pruv_after: &%s, pruv_before: &%s, pruv_kk: %s, pruv_vv: %s, pruv_budget: &mut i64) -> bool {" % (
                 name, M, M, cty(kt), cty(vt)),
             "    let pruv_nk: %s = match %s { Some(pruv_x) => pruv_x, None => return false };" % (K, keyconv),
             "    let pruv_was: bool = pruv_before.contains_key(&pruv_nk);",
             "    if pruv_after.len() != pruv_before.len() + (if pruv_was { 0 } else { 1 }) { return false; }",
             "    match pruv_after.get(&pruv_nk) { Some(pruv_a) => { if !(%s == pruv_vv) { return false; } } "
             "None => { return false; } }" % conv(vt, "(*pruv_a)"),
             "    for (pruv_bk, pruv_bv) in pruv_before.iter() {",
             "        *pruv_budget -= 1; if *pruv_budget < 0 { pruv_ud(\"contract iteration budget exceeded\"); }",
             "        if *pruv_bk != pruv_nk {",
             "            match pruv_after.get(pruv_bk) { Some(pruv_av) => { if !(%s == %s) { return false; } } "
             "None => { return false; } }" % (conv(vt, "(*pruv_av)"), conv(vt, "(*pruv_bv)")),
             "        }",
             "    }",
             "    true",
             "}"]
        s.items[name] = "\n".join(L) + "\n"
        s.catalog.append({"op": "map_updated", "type_args": [format_type(t) for t in src]})
        return name

    # ------------------------------------------------------------------ trusted rust fn
    def trusted_helper(s, f):
        """private helper `NAME`: selected requires, catch_unwind around the Rust call, selected ensures"""
        name = f.name
        if name in s.items:
            return name
        g = s.g
        s.op = name
        disp = getattr(f, "disp", name)     # G4 A2: messages name the source identity, the helper keeps its stem
        saved = (g.params, g.vt, g.cp, g.bound, g.tmp, g.borrowed)
        g.params = set(p.name for p in f.params) | {"result"}
        g.vt = dict((p.name, p.type) for p in f.params)
        g.cp, g.bound, g.tmp, g.borrowed = None, [], 0, set()
        try:
            body = []
            if s.req:
                for r in f.requires:
                    body.append("if !(%s) { pruv_g6_req(%s, %s); }" % (g.c(r), rstr(disp), rstr(show(r))))
            args = ", ".join(p.name for p in f.params)
            rt = rty(f.ret)
            body.append("let result: %s = match ::std::panic::catch_unwind(::std::panic::AssertUnwindSafe(|| %s(%s))) {" % (
                rt, f.foreign["path"], args))
            body.append("    Ok(pruv_r) => pruv_r,")
            body.append("    Err(_) => panic!(%s)," % rstr("pruv: foreign panic: " + disp))
            body.append("};")
            if s.ens:
                for x in f.ensures:
                    body.append("if !(%s) { pruv_g6_ens(%s, %s); }" % (g.c(x), rstr(disp), rstr(show(x))))
            body.append("result")
            ps = ", ".join("%s: %s" % (p.name, rty(p.type, True)) for p in f.params)
            text = s._fn_trusted(name, ps, None if f.ret == UNIT else rt, body, disp)
        finally:
            g.params, g.vt, g.cp, g.bound, g.tmp, g.borrowed = saved
        s.items[name] = text
        return name

    def _fn_trusted(s, name, params, ret, body, disp=None):
        g = s.g
        L = [g.allow, "fn %s(%s)%s {" % (name, params, "" if ret is None else " -> " + ret)]
        if s.req:
            L.append("    let pruv_g = pruv_ctx(%s);" % rstr(name if disp is None else disp))
            L.append("    " + _budget_line(g.budget))   # shared by requires and ensures of one call
        L.extend("    " + x for x in body)
        L.append("}")
        return "\n".join(L) + "\n"
