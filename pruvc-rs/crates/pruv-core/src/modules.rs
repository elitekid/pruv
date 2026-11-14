//! G4 A0: program files, name resolution and visibility (counterpart of pruvc/modules.py; docs/G4_SPEC.md sections 2, 3, 5, 8, 10).
//!
//! `load_program(path)`  the file-taking entry point. A root with neither `mod` nor a top-level `pub` is returned exactly as
//!                       the parser produced it (legacy mode, `g4` is None). Otherwise the explicit visibility mode is active
//!                       for the whole program: the declared child files are loaded (root first, depth first, declaration
//!                       order) and `Program.functions` / `types` hold the items of all modules in that order.
//! `resolve(prog, g4)`   explicit mode only (called by check::check_explicit): validates declaration names, replaces every
//!                       lookup key by the item's resolved identity `crate::a::b::name` (root items `crate::name`), checks
//!                       access (private_item), public interfaces (public_interface) and the root main, and sets the
//!                       host-entry classification.
//!
//! Python tags every node with its `file`; here the source file of a node is the tag in its line number (diagnostic.rs),
//! so a diagnostic carries `file` without any change of the AST. `Function.pub` / `src_name` / `mod_path` / `host_entry`
//! are the parallel vectors `G4.fn_meta` / `ty_meta` (same indices as `Program.functions` / `types`).

use crate::ast::*;
use crate::diagnostic::{set_files, tagged_line, PruvError};
use crate::foreign::is_catalog;
use crate::gtype::{decl_owner, dependencies, fn_owner, GType};
use crate::pyio::{io_error_message, utf8_error_message};
use crate::typeinfo::BUILTIN_TYPE_NAMES;
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

type Res<T> = Result<T, PruvError>;

/// vparser / check names that a function may not carry (check.py BUILTIN_FNS).
const BUILTIN_FNS: [&str; 16] = [
    "len", "alloc", "copy", "print", "is_char_boundary", "substr", "truncate", "band", "bor", "bxor", "wrapping_shl",
    "ushr", "wrapping_add", "wrapping_mul", "load_be", "store_be",
];

/// Display form of a module path: crate, crate::a, crate::a::b.
pub fn disp(path: &[String]) -> String {
    let mut s = "crate".to_string();
    for p in path {
        s.push_str("::");
        s.push_str(p);
    }
    s
}

/// The identity of an item: crate::a::b::name (root items crate::name).
pub fn ident(path: &[String], name: &str) -> String {
    format!("{}::{}", disp(path), name)
}

/// G4 A2 (docs/G4_SPEC.md 6; Python `encode_name`): the count of the components, then for each one `_<ASCII byte length>_<component>`.
pub fn encode_name(components: &[String]) -> String {
    let mut s = components.len().to_string();
    for c in components {
        s.push_str(&format!("_{}_{}", c.len(), c));
    }
    s
}

/// Rust stem of an item in explicit mode (Python `encode_stem`): kind "f" (function) or "t" (nominal type); components = the
/// module path followed by the item's source name.
pub fn encode_stem(kind: &str, components: &[String]) -> String {
    format!("pruv_m_{}_{}", kind, encode_name(components))
}

/// "crate::a::b::x" -> ["a", "b", "x"] (Python `identity_components`)
pub fn identity_components(identity: &str) -> Vec<String> {
    identity.split("::").skip(1).map(|s| s.to_string()).collect()
}

/// A type whose nominal names (identities) are replaced by their `encode_name` (Python `safe_type`), so that the G3 stem and
/// argument encodings only ever see [0-9A-Za-z_] names; injective like the identity.
pub fn safe_type(ty: &GType) -> GType {
    safe_type_cow(ty).into_owned()
}

/// `safe_type` that borrows a type it leaves unchanged (legacy types and builtin-only trees are never copied)
pub fn safe_type_cow(ty: &GType) -> std::borrow::Cow<'_, GType> {
    use std::borrow::Cow;
    if ty.owner.is_some() {
        return Cow::Borrowed(ty);
    }
    let args: Vec<Cow<'_, GType>> = ty.args.iter().map(safe_type_cow).collect();
    if BUILTIN_TYPE_NAMES.contains(&ty.name.as_str()) || !ty.name.starts_with("crate::") {
        if args.iter().all(|a| matches!(a, Cow::Borrowed(_))) {
            return Cow::Borrowed(ty);
        }
        return Cow::Owned(GType::new(&ty.name, args.into_iter().map(Cow::into_owned).collect()));
    }
    Cow::Owned(GType::new(&encode_name(&identity_components(&ty.name)), args.into_iter().map(Cow::into_owned).collect()))
}

#[derive(Debug, Clone)]
pub struct Module {
    /// module names from the root; empty is the root
    pub path: Vec<String>,
    /// path relative to the root directory, `/` separators
    pub file: String,
    pub parent: Option<usize>,
    /// ModDecl list in source order (duplicates included)
    pub mods: Vec<ModDecl>,
    /// name -> loaded child (a duplicate declaration is not loaded again)
    pub children: Vec<(String, usize)>,
    /// the items of this module in source order (indices into Program.functions / types)
    pub items: Vec<Item>,
    /// source name -> index into Program.functions (filled by resolve)
    pub funcs: HashMap<String, usize>,
    /// source name -> index into Program.types (filled by resolve)
    pub types: HashMap<String, usize>,
}

impl Module {
    fn new(path: Vec<String>, file: String, parent: Option<usize>) -> Module {
        Module {
            path,
            file,
            parent,
            mods: Vec::new(),
            children: Vec::new(),
            items: Vec::new(),
            funcs: HashMap::new(),
            types: HashMap::new(),
        }
    }

    fn child(&self, name: &str) -> Option<usize> {
        self.children.iter().find(|(n, _)| n == name).map(|(_, i)| *i)
    }
}

/// The explicit-mode attributes of one function / type declaration.
#[derive(Debug, Clone)]
pub struct ItemMeta {
    /// index into G4.modules of the defining module
    pub module: usize,
    /// `pub`
    pub is_pub: bool,
    /// the name as written (Function.name / the declaration name then hold the resolved identity)
    pub src_name: String,
    /// root `pub` nongeneric ordinary function (set by resolve)
    pub host_entry: bool,
}

/// Explicit-mode data of a program (Python `Program.explicit` / `modules` / `items` / `entries` / `main`).
#[derive(Debug, Clone)]
pub struct G4 {
    /// root-first depth-first order
    pub modules: Vec<Module>,
    /// all items in program order
    pub items: Vec<Item>,
    pub fn_meta: Vec<ItemMeta>,
    pub ty_meta: Vec<ItemMeta>,
    /// identities of the host entries (after resolve)
    pub entries: Vec<String>,
    /// identity of the root main (after resolve)
    pub main: Option<String>,
    pub resolved: bool,
}

pub struct Loaded {
    pub prog: Program,
    /// Some in explicit mode
    pub g4: Option<G4>,
}

pub enum LoadError {
    /// the root file cannot be read (Python OSError message)
    Io(String),
    /// the root file is not UTF-8 (Python UnicodeDecodeError message)
    Decode(String),
    /// a language error (parse / module_file / module_alias)
    Lang(PruvError),
}

// ---------------------------------------------------------------------------
// loading
// ---------------------------------------------------------------------------

/// the identity of a file (device, inode), computed once per loaded file; None when the file cannot be inspected
#[cfg(unix)]
fn file_id(a: &Path) -> Option<String> {
    use std::os::unix::fs::MetadataExt;
    std::fs::metadata(a).ok().map(|x| format!("{}:{}", x.dev(), x.ino()))
}

#[cfg(not(unix))]
fn file_id(a: &Path) -> Option<String> {
    a.canonicalize().ok().map(|x| x.to_string_lossy().into_owned())
}

struct Loader {
    root_dir: PathBuf,
    modules: Vec<Module>,
    parsed: Vec<crate::parser::ParsedFile>,
    /// file identity -> display path of every loaded file
    loaded: HashMap<String, String>,
}

impl Loader {
    /// Registers the file names of the modules loaded so far (diagnostic line tags), plus one pending file.
    fn publish(&self, extra: Option<&str>) {
        let mut v: Vec<String> = self.modules.iter().map(|m| m.file.clone()).collect();
        if let Some(x) = extra {
            v.push(x.to_string());
        }
        set_files(v);
    }

    fn visit(&mut self, mi: usize) -> Res<()> {
        let mut seen: HashSet<String> = HashSet::new();
        let mods = self.modules[mi].mods.clone();
        for md in &mods {
            if !seen.insert(md.name.clone()) {
                continue; // reported by resolve as type/duplicate_module; the file is loaded once
            }
            let mut cpath = self.modules[mi].path.clone();
            cpath.push(md.name.clone());
            let mut rel = format!("{}.pruv", cpath.join("/"));
            let mut fp = self.root_dir.clone();
            for c in &cpath {
                fp.push(c);
            }
            let fpath = PathBuf::from(format!("{}.pruv", fp.to_string_lossy()));
            let text = if md.name == "std" {
                if !self.modules[mi].path.is_empty() {
                    return Err(PruvError::new(
                        "parse", md.line, md.col, "std_import_location",
                        "std may only be imported at the program root",
                        "move `mod std;` to the root and call `crate::std::name`",
                    ));
                }
                // Like lexists: directories and dangling symlinks also conflict.
                if std::fs::symlink_metadata(&fpath).is_ok() {
                    return Err(PruvError::new(
                        "parse", md.line, md.col, "std_module_conflict",
                        "local std.pruv conflicts with the bundled std module",
                        "rename the user module/file and its paths",
                    ));
                }
                rel = "@std/std.pruv".to_string();
                // Embed bytes so invalid UTF-8 retains the import-site diagnostic.
                std::str::from_utf8(include_bytes!("../../../../stdlib/std.pruv"))
                    .map_err(|_| PruvError::new(
                        "parse", md.line, md.col, "std_source",
                        "cannot read the bundled std module as UTF-8",
                        "restore/reinstall the matching compiler resource",
                    ))?.to_string()
            } else {
                match std::fs::read(&fpath) {
                    Ok(bytes) => match String::from_utf8(bytes) {
                        Ok(s) => s,
                        Err(_) => {
                            return Err(PruvError::new(
                                "parse",
                                md.line,
                                md.col,
                                "module_file",
                                format!("the file of module {} is not valid UTF-8", disp(&cpath)),
                                format!("save {} as UTF-8", rel),
                            ));
                        }
                    },
                    Err(_) => {
                        return Err(PruvError::new(
                            "parse",
                            md.line,
                            md.col,
                            "module_file",
                            format!("cannot read the file of module {} (expected {})", disp(&cpath), rel),
                            format!("create {} next to the root file, or remove `mod {};`", rel, md.name),
                        ));
                    }
                }
            };
            let fid = if md.name == "std" { None } else { file_id(&fpath) };
            if let Some(orel) = fid.as_ref().and_then(|k| self.loaded.get(k)) {
                return Err(PruvError::new(
                    "parse",
                    md.line,
                    md.col,
                    "module_alias",
                    format!("the file {} of module {} was already loaded as {}", rel, disp(&cpath), orel),
                    "every module needs its own file; remove the alias",
                ));
            }
            if let Some(k) = fid {
                self.loaded.insert(k, rel.clone());
            }
            let tag = self.modules.len() + 1;
            let parsed = match crate::parser::parse_file(&text, tag) {
                Ok(p) => p,
                Err(e) => {
                    self.publish(Some(&rel)); // the error carries the tag of this file
                    return Err(e);
                }
            };
            let ci = self.modules.len();
            let mut child = Module::new(cpath, rel, Some(mi));
            child.mods = parsed.mods.clone();
            self.modules[mi].children.push((md.name.clone(), ci));
            self.modules.push(child);
            self.parsed.push(parsed);
            self.publish(None);
            self.visit(ci)?;
        }
        Ok(())
    }
}

/// Reads the root file (same failures as Python `open(path).read()`) and loads the program.
pub fn load_program(path: &Path) -> Result<Loaded, LoadError> {
    let bytes = std::fs::read(path).map_err(|e| LoadError::Io(io_error_message(path, &e)))?;
    let src = match std::str::from_utf8(&bytes) {
        Ok(s) => s.to_string(),
        Err(e) => return Err(LoadError::Decode(utf8_error_message(&bytes, &e))),
    };
    load_source(path, &src)
}

/// `load_program` for an already decoded root text (`path` still names the root: children are relative to its directory).
pub fn load_source(path: &Path, src: &str) -> Result<Loaded, LoadError> {
    let root_file = path.file_name().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default();
    let first = match crate::parser::parse_file(src, 0) {
        Ok(f) => f,
        Err(mut e) => {
            set_files(Vec::new());
            if e.stage != "internal" && crate::parser::sniff_explicit(src) {
                // a root that uses module syntax: its error carries `file`
                set_files(vec![root_file]);
                e.line = tagged_line(e.line, 1);
            }
            return Err(LoadError::Lang(e));
        }
    };
    if first.mods.is_empty() && !first.has_pub {
        set_files(Vec::new());
        return Ok(Loaded { prog: first.prog, g4: None }); // legacy mode: untouched
    }
    // explicit mode: the root is parsed again with its file tag
    let root = match crate::parser::parse_file(src, 1) {
        Ok(f) => f,
        Err(e) => {
            set_files(vec![root_file]);
            return Err(LoadError::Lang(e));
        }
    };
    let abs = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir().map(|d| d.join(path)).unwrap_or_else(|_| path.to_path_buf())
    };
    let root_dir = abs.parent().map(|p| p.to_path_buf()).unwrap_or_default();
    let mut root_mod = Module::new(Vec::new(), root_file.clone(), None);
    root_mod.mods = root.mods.clone();
    let mut loaded = HashMap::new();
    if let Some(k) = file_id(&abs) {
        loaded.insert(k, root_file);
    }
    let mut ld = Loader { root_dir, modules: vec![root_mod], parsed: vec![root], loaded };
    ld.publish(None);
    ld.visit(0).map_err(LoadError::Lang)?;

    // the flat program: the items of all modules in module order
    let Loader { mut modules, parsed, .. } = ld;
    let mut prog = Program::default();
    let mut all_items: Vec<Item> = Vec::new();
    let mut fn_meta: Vec<ItemMeta> = Vec::new();
    let mut ty_meta: Vec<ItemMeta> = Vec::new();
    for (mi, pf) in parsed.into_iter().enumerate() {
        let crate::parser::ParsedFile { prog: pp, items, fn_pub, ty_pub, .. } = pf;
        let mut fns: Vec<Option<Function>> = pp.functions.into_iter().map(Some).collect();
        let mut tys: Vec<Option<TypeDecl>> = pp.types.into_iter().map(Some).collect();
        let mut mitems: Vec<Item> = Vec::new();
        for it in items {
            match it {
                Item::Fn(i) => {
                    if let Some(f) = fns[i].take() {
                        let gi = prog.functions.len();
                        fn_meta.push(ItemMeta { module: mi, is_pub: fn_pub[i], src_name: f.name.clone(), host_entry: false });
                        prog.functions.push(f);
                        mitems.push(Item::Fn(gi));
                    }
                }
                Item::Ty(i) => {
                    if let Some(d) = tys[i].take() {
                        let gi = prog.types.len();
                        ty_meta.push(ItemMeta { module: mi, is_pub: ty_pub[i], src_name: d.name().to_string(), host_entry: false });
                        prog.types.push(d);
                        mitems.push(Item::Ty(gi));
                    }
                }
            }
        }
        modules[mi].items = mitems.clone();
        all_items.extend(mitems);
    }
    let g4 = G4 { modules, items: all_items, fn_meta, ty_meta, entries: Vec::new(), main: None, resolved: false };
    Ok(Loaded { prog, g4: Some(g4) })
}

// ---------------------------------------------------------------------------
// resolution
// ---------------------------------------------------------------------------

fn err(line: i64, col: i64, code: &str, msg: impl Into<String>, fix: impl Into<String>) -> PruvError {
    PruvError::new("type", line, col, code, msg, fix)
}

pub fn resolve(prog: &mut Program, g4: &mut G4) -> Res<()> {
    if g4.resolved {
        return Ok(());
    }
    g4.resolved = true;
    run(prog, g4)
}

fn tparams_of(prog: &Program, it: Item) -> Vec<TParam> {
    match it {
        Item::Fn(i) => prog.functions[i].tparams.clone(),
        Item::Ty(i) => prog.types[i].tparams().to_vec(),
    }
}

fn run(prog: &mut Program, g4: &mut G4) -> Res<()> {
    // 1. declaration names per module (functions, then types, like the legacy checker), module declarations
    for mi in 0..g4.modules.len() {
        let items = g4.modules[mi].items.clone();
        let path = g4.modules[mi].path.clone();
        for it in &items {
            if let Item::Fn(fi) = *it {
                let f = &prog.functions[fi];
                if g4.modules[mi].funcs.contains_key(&f.name) {
                    return Err(err(f.line, f.col, "dup_fn", format!("function {} defined twice", ident(&path, &f.name)), ""));
                }
                if BUILTIN_FNS.contains(&f.name.as_str()) || crate::check::contract_only(&f.name).is_some() || is_catalog(&f.name) {
                    return Err(err(f.line, f.col, "reserved", format!("{} is a builtin name", f.name), "rename the function"));
                }
                g4.modules[mi].funcs.insert(f.name.clone(), fi);
            }
        }
        for it in &items {
            if let Item::Ty(ti) = *it {
                let d = &prog.types[ti];
                let (name, line, col) = (d.name().to_string(), d.line(), d.col());
                if !crate::check::type_name_ok(&name) {
                    return Err(err(
                        line,
                        col,
                        "type_name",
                        format!("type name {} must start with an upper-case letter", name),
                        format!("rename it, e.g. {}", crate::check::cap_first(&name, true)),
                    ));
                }
                if crate::check::RESERVED_TYPE_NAMES.contains(&name.as_str()) {
                    return Err(err(line, col, "reserved", format!("{} is a builtin name", name), "rename the type"));
                }
                if g4.modules[mi].types.contains_key(&name) {
                    return Err(err(line, col, "dup_type", format!("type {} defined twice", ident(&path, &name)), ""));
                }
                if g4.modules[mi].funcs.contains_key(&name) {
                    return Err(err(
                        line,
                        col,
                        "name_collision",
                        format!("{} is both a type and a function", ident(&path, &name)),
                        "rename the type or the function",
                    ));
                }
                g4.modules[mi].types.insert(name, ti);
            }
        }
        let mut seen: HashSet<String> = HashSet::new();
        let mods = g4.modules[mi].mods.clone();
        for md in &mods {
            if seen.contains(&md.name) {
                return Err(err(
                    md.line,
                    md.col,
                    "duplicate_module",
                    format!("module {} is declared twice in {}", md.name, disp(&path)),
                    format!("remove the second `mod {};`", md.name),
                ));
            }
            seen.insert(md.name.clone());
            if g4.modules[mi].funcs.contains_key(&md.name) {
                return Err(err(
                    md.line,
                    md.col,
                    "name_collision",
                    format!("{} is both a module and a function in {}", md.name, disp(&path)),
                    "rename the module or the function",
                ));
            }
        }
    }
    // 1b. a type parameter may not carry the name of a type of its module (builtin names: the checker)
    let items = g4.items.clone();
    for it in &items {
        let mi = match *it {
            Item::Fn(i) => g4.fn_meta[i].module,
            Item::Ty(i) => g4.ty_meta[i].module,
        };
        for tp in tparams_of(prog, *it) {
            if g4.modules[mi].types.contains_key(&tp.name) {
                return Err(err(
                    tp.line,
                    tp.col,
                    "type_parameter",
                    format!("type parameter {} shadows a declared or built-in type", tp.name),
                    "choose a name that is not a type, e.g. T",
                ));
            }
        }
    }
    // 2. resolve every reference (items in program order); then rename the items to their identities
    {
        let g4r: &G4 = &*g4;
        let mut rs = Rs { g4: g4r, cur: 0, old_owner: String::new(), new_owner: String::new() };
        for it in &items {
            match *it {
                Item::Fn(fi) => {
                    rs.cur = g4r.fn_meta[fi].module;
                    rs.fn_(&mut prog.functions[fi], &g4r.fn_meta[fi])?;
                }
                Item::Ty(ti) => {
                    rs.cur = g4r.ty_meta[ti].module;
                    rs.tdecl(&mut prog.types[ti], &g4r.ty_meta[ti])?;
                }
            }
        }
    }
    // 3. public interfaces (G4 A1: transitive over the field / payload types of public declarations). The map is built
    // after resolution, so the field types are already identities.
    let mut type_by_id: HashMap<String, TyIface> = HashMap::new();
    for m in &g4.modules {
        for (name, ti) in &m.types {
            let fields: Vec<(String, GType)> = decl_fields(&prog.types[*ti])
                .into_iter()
                .map(|fd| (fd.name.clone(), GType::from_key(&fd.ty)))
                .collect();
            type_by_id.insert(ident(&m.path, name), TyIface { is_pub: g4.ty_meta[*ti].is_pub, fields });
        }
    }
    // one visited set for the whole program: the first leak aborts the check, so every public declaration visited by an
    // earlier item has a closure without private declarations and need not be walked again
    let mut iface_seen: HashSet<String> = HashSet::new();
    for it in &items {
        match *it {
            Item::Fn(fi) => {
                if g4.fn_meta[fi].is_pub {
                    iface_fn(&type_by_id, &prog.functions[fi], &mut iface_seen)?;
                }
            }
            Item::Ty(ti) => {
                if g4.ty_meta[ti].is_pub {
                    iface_ty(&type_by_id, &prog.types[ti], &mut iface_seen)?;
                }
            }
        }
    }
    // 4. root main and host entries
    entries(prog, g4)
}

/// resolver state (Python `_Resolver`): the module tree is read-only here, the items are rewritten in place
struct Rs<'a> {
    g4: &'a G4,
    /// the module of the item being resolved
    cur: usize,
    old_owner: String,
    new_owner: String,
}

impl<'a> Rs<'a> {
    fn module(&self, i: usize) -> &'a Module {
        let g: &'a G4 = self.g4;
        &g.modules[i]
    }

    /// crate::a::b::x -> (innermost module reached by module segments, remaining segments)
    fn walk(&self, path: &str) -> (usize, Vec<String>) {
        let segs: Vec<&str> = path.split("::").skip(1).collect();
        let mut m = 0usize;
        let mut i = 0usize;
        while i + 1 < segs.len() {
            match self.module(m).child(segs[i]) {
                Some(c) => {
                    m = c;
                    i += 1;
                }
                None => break,
            }
        }
        (m, segs[i..].iter().map(|s| s.to_string()).collect())
    }

    fn access(&self, is_pub: bool, m: usize, line: i64, col: i64, path: &str) -> Res<()> {
        if !is_pub && m != self.cur {
            let md = self.module(m);
            return Err(err(
                line,
                col,
                "private_item",
                format!("{} is private to module {}", path, disp(&md.path)),
                format!("mark it `pub` in {}, or call it through a public item of that module", md.file),
            ));
        }
        Ok(())
    }

    fn unknown_module(&self, m: usize, rem: &[String], line: i64, col: i64, path: &str) -> PruvError {
        let md = self.module(m);
        err(
            line,
            col,
            "unknown_module",
            format!("unknown module {} in {} (path {})", rem[0], disp(&md.path), path),
            format!("declare it with `mod {};` in {}, or correct the path", rem[0], md.file),
        )
    }

    fn type_item(&self, path: &str, line: i64, col: i64) -> Res<String> {
        let (m, rem) = self.walk(path);
        if rem.len() > 1 {
            return Err(self.unknown_module(m, &rem, line, col, path));
        }
        let md = self.module(m);
        let ti = match md.types.get(&rem[0]) {
            Some(t) => *t,
            None => {
                if md.child(&rem[0]).is_some() {
                    return Err(err(line, col, "unknown_type", format!("{} is a module, not a type", path), "name a struct or enum of the module"));
                }
                return Err(err(
                    line,
                    col,
                    "unknown_type",
                    format!("unknown type {}", path),
                    format!("declare it with `struct`/`enum` in {}", md.file),
                ));
            }
        };
        self.access(self.g4.ty_meta[ti].is_pub, m, line, col, path)?;
        Ok(ident(&md.path, &rem[0]))
    }

    /// a nominal name as written -> identity (qualified: resolved; unqualified: the current module only; otherwise
    /// unchanged: builtin/catalog spelling or an unknown name for the checker)
    fn local_or_path_type(&self, name: &str, line: i64, col: i64) -> Res<String> {
        if name.starts_with("crate::") {
            return self.type_item(name, line, col);
        }
        let cur = self.module(self.cur);
        if cur.types.contains_key(name) {
            return Ok(ident(&cur.path, name));
        }
        Ok(name.to_string())
    }

    fn fn_item(&self, m: usize, rem: &[String], line: i64, col: i64, path: &str) -> Res<String> {
        if rem.len() != 1 {
            return Err(self.unknown_module(m, rem, line, col, path));
        }
        let md = self.module(m);
        let fi = match md.funcs.get(&rem[0]) {
            Some(f) => *f,
            None => {
                if md.child(&rem[0]).is_some() {
                    return Err(err(line, col, "unknown_fn", format!("{} is a module, not a function", path), "name a function of the module"));
                }
                return Err(err(line, col, "unknown_fn", format!("unknown function {}", path), format!("declare it in {}", md.file)));
            }
        };
        self.access(self.g4.fn_meta[fi].is_pub, m, line, col, path)?;
        Ok(ident(&md.path, &rem[0]))
    }

    // ---- types ----
    fn rtype(&self, ty: &GType, line: i64, col: i64) -> Res<GType> {
        if let Some(owner) = &ty.owner {
            if *owner == self.old_owner {
                return Ok(GType { name: ty.name.clone(), args: ty.args.clone(), owner: Some(self.new_owner.clone()), index: ty.index });
            }
            return Ok(ty.clone());
        }
        if ty.args.is_empty() && BUILTIN_TYPE_NAMES.contains(&ty.name.as_str()) {
            return Ok(ty.clone());
        }
        let mut args: Vec<GType> = Vec::with_capacity(ty.args.len());
        for a in &ty.args {
            args.push(self.rtype(a, line, col)?);
        }
        let name = if BUILTIN_TYPE_NAMES.contains(&ty.name.as_str()) {
            ty.name.clone()
        } else {
            self.local_or_path_type(&ty.name, line, col)?
        };
        if name == ty.name && args == ty.args {
            return Ok(ty.clone());
        }
        Ok(GType::new(&name, args))
    }

    /// `rtype` on an AST type key (an unchanged type keeps its key text)
    fn rtype_key(&self, key: &str, line: i64, col: i64) -> Res<String> {
        let g = GType::from_key(key);
        let r = self.rtype(&g, line, col)?;
        if r == g {
            Ok(key.to_string())
        } else {
            Ok(r.to_key())
        }
    }

    fn targs(&self, targs: &mut Option<Vec<GType>>, line: i64, col: i64) -> Res<()> {
        if let Some(v) = targs {
            let mut out: Vec<GType> = Vec::with_capacity(v.len());
            for t in v.iter() {
                out.push(self.rtype(t, line, col)?);
            }
            *v = out;
        }
        Ok(())
    }

    fn rrefine(&self, r: &mut Option<Refinement>) -> Res<()> {
        if let Some(r) = r {
            if !BUILTIN_TYPE_NAMES.contains(&r.base.as_str()) {
                r.base = self.local_or_path_type(&r.base, r.line, r.col)?;
            }
        }
        Ok(())
    }

    // ---- items ----
    fn tdecl(&mut self, d: &mut TypeDecl, meta: &ItemMeta) -> Res<()> {
        let path = &self.module(meta.module).path;
        self.old_owner = decl_owner(&meta.src_name);
        self.new_owner = decl_owner(&ident(path, &meta.src_name));
        let new_name = ident(path, &meta.src_name);
        match d {
            TypeDecl::Struct(s) => {
                for fd in s.fields.iter_mut() {
                    fd.ty = self.rtype_key(&fd.ty, fd.line, fd.col)?;
                }
                s.name = new_name;
            }
            TypeDecl::Enum(e) => {
                for v in e.variants.iter_mut() {
                    for fd in v.fields.iter_mut() {
                        fd.ty = self.rtype_key(&fd.ty, fd.line, fd.col)?;
                    }
                }
                e.name = new_name;
            }
        }
        Ok(())
    }

    fn fn_(&mut self, f: &mut Function, meta: &ItemMeta) -> Res<()> {
        let path = &self.module(meta.module).path;
        self.old_owner = fn_owner(&meta.src_name);
        self.new_owner = fn_owner(&ident(path, &meta.src_name));
        let (fl, fc) = (f.line, f.col);
        for p in f.params.iter_mut() {
            p.ty = self.rtype_key(&p.ty, fl, fc)?;
            self.rrefine(&mut p.refine)?;
        }
        f.ret = self.rtype_key(&f.ret, fl, fc)?;
        self.rrefine(&mut f.ret_refine)?;
        for e in f.requires.iter_mut() {
            self.rexpr(e)?;
        }
        for e in f.ensures.iter_mut() {
            self.rexpr(e)?;
        }
        if let Some(d) = f.cost.as_mut() { self.rexpr(d)?; }
        if let Some(d) = f.decreases.as_mut() {
            self.rexpr(d)?;
        }
        self.rstmts(&mut f.body)?;
        f.name = ident(path, &meta.src_name);
        Ok(())
    }

    // ---- statements ----
    fn rstmts(&self, stmts: &mut [Stmt]) -> Res<()> {
        for st in stmts.iter_mut() {
            match st {
                Stmt::Let(l) => {
                    l.ty = self.rtype_key(&l.ty, l.line, l.col)?;
                    self.rrefine(&mut l.refine)?;
                    self.rexpr(&mut l.value)?;
                }
                Stmt::Assign(a) => self.rexpr(&mut a.value)?,
                Stmt::FieldAssign(a) => self.rexpr(&mut a.value)?,
                Stmt::IndexAssign(a) => {
                    self.rexpr(&mut a.index)?;
                    self.rexpr(&mut a.value)?;
                }
                Stmt::If(i) => {
                    self.rexpr(&mut i.cond)?;
                    self.rstmts(&mut i.then)?;
                    self.rstmts(&mut i.els)?;
                }
                Stmt::While(w) => {
                    self.rexpr(&mut w.cond)?;
                    for e in w.invariants.iter_mut() {
                        self.rexpr(e)?;
                    }
                    self.rexpr(&mut w.decreases)?;
                    self.rstmts(&mut w.body)?;
                }
                Stmt::Return(r) => {
                    if let Some(v) = r.value.as_mut() {
                        self.rexpr(v)?;
                    }
                }
                Stmt::Assert(a) => self.rexpr(&mut a.cond)?,
                Stmt::Par(x) => {
                    for c in &mut x.calls {
                        self.rexpr(c)?;
                    }
                }
                Stmt::ExprStmt(x) => self.rexpr(&mut x.expr)?,
                Stmt::Match(m) => {
                    self.rexpr(&mut m.scrutinee)?;
                    for a in m.arms.iter_mut() {
                        if let Some(en) = &a.enum_name {
                            let n = self.local_or_path_type(en, a.line, a.col)?;
                            a.enum_name = Some(n);
                        }
                        self.rstmts(&mut a.body)?;
                    }
                }
            }
        }
        Ok(())
    }

    // ---- expressions ----
    fn rexpr(&self, e: &mut Expr) -> Res<()> {
        // `crate::m::Enum::Variant(args)` parses as a Call: a variant constructor replaces the node
        let mut replace: Option<Expr> = None;
        if let Expr::Call(c) = &mut *e {
            if c.name.starts_with("crate::") {
                let (m, rem) = self.walk(&c.name);
                if rem.len() == 2 && c.targs.is_none() && self.module(m).types.contains_key(&rem[0]) {
                    if c.args.is_empty() {
                        let prefix = match c.name.rfind("::") {
                            Some(i) => c.name[..i].to_string(),
                            None => c.name.clone(),
                        };
                        return Err(PruvError::new(
                            "parse",
                            c.line,
                            c.col,
                            "syntax",
                            "empty parentheses after a variant",
                            format!("write `{}::{}` for a variant without fields, or pass its fields as arguments", prefix, rem[1]),
                        ));
                    }
                    let md = self.module(m);
                    let ti = md.types[&rem[0]];
                    self.access(self.g4.ty_meta[ti].is_pub, m, c.line, c.col, &format!("{}::{}", disp(&md.path), rem[0]))?;
                    let args = std::mem::take(&mut c.args);
                    replace = Some(Expr::EnumCtor(EnumCtor {
                        line: c.line,
                        col: c.col,
                        enum_name: ident(&md.path, &rem[0]),
                        variant: rem[1].clone(),
                        args,
                        ty: None,
                        targs: None,
                        inst: None,
                    }));
                }
            }
        }
        if let Some(mut n) = replace {
            if let Expr::EnumCtor(ec) = &mut n {
                for a in ec.args.iter_mut() {
                    self.rexpr(a)?;
                }
            }
            *e = n;
            return Ok(());
        }
        match e {
            Expr::Call(c) => {
                if c.name.starts_with("crate::") {
                    let (m, rem) = self.walk(&c.name);
                    let nm = self.fn_item(m, &rem, c.line, c.col, &c.name)?;
                    c.name = nm;
                } else {
                    let cur = self.module(self.cur);
                    if cur.funcs.contains_key(&c.name) {
                        c.name = ident(&cur.path, &c.name);
                    }
                }
                self.targs(&mut c.targs, c.line, c.col)?;
                for a in c.args.iter_mut() {
                    self.rexpr(a)?;
                }
            }
            Expr::EnumCtor(x) => {
                x.enum_name = self.local_or_path_type(&x.enum_name, x.line, x.col)?;
                self.targs(&mut x.targs, x.line, x.col)?;
                for a in x.args.iter_mut() {
                    self.rexpr(a)?;
                }
            }
            Expr::StructLit(x) => {
                x.name = self.local_or_path_type(&x.name, x.line, x.col)?;
                self.targs(&mut x.targs, x.line, x.col)?;
                for fi in x.fields.iter_mut() {
                    self.rexpr(&mut fi.value)?;
                }
            }
            Expr::IsVariant(x) => {
                x.enum_name = self.local_or_path_type(&x.enum_name, x.line, x.col)?;
                self.rexpr(&mut x.value)?;
            }
            Expr::VariantField(x) => {
                x.enum_name = self.local_or_path_type(&x.enum_name, x.line, x.col)?;
                self.rexpr(&mut x.value)?;
            }
            Expr::Ctor(x) => {
                self.targs(&mut x.targs, x.line, x.col)?;
                if let Some(a) = x.arg.as_mut() {
                    self.rexpr(a)?;
                }
            }
            Expr::Unary(x) => self.rexpr(&mut x.operand)?,
            Expr::Binary(x) => {
                self.rexpr(&mut x.left)?;
                self.rexpr(&mut x.right)?;
            }
            Expr::Index(x) => {
                self.rexpr(&mut x.array)?;
                self.rexpr(&mut x.index)?;
            }
            Expr::Quant(x) => {
                self.rexpr(&mut x.lo)?;
                self.rexpr(&mut x.hi)?;
                self.rexpr(&mut x.body)?;
            }
            Expr::FieldAccess(x) => self.rexpr(&mut x.base)?,
            Expr::InoutArg(x) => self.rexpr(&mut x.expr)?, // G5 A0
            Expr::Spent(_) | Expr::IntLit(_) | Expr::BoolLit(_) | Expr::StrLit(_) | Expr::Var(_) | Expr::Move(_) => {}
        }
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// public interfaces
// ---------------------------------------------------------------------------

/// visibility and field / payload types (in declaration order) of one declared type, by identity
struct TyIface {
    is_pub: bool,
    fields: Vec<(String, GType)>,
}

/// the fields of a declaration (Python `decl_fields`): struct fields, or the payload fields of every variant in order
fn decl_fields(d: &TypeDecl) -> Vec<&FieldDecl> {
    match d {
        TypeDecl::Struct(s) => s.fields.iter().collect(),
        TypeDecl::Enum(e) => e.variants.iter().flat_map(|v| v.fields.iter()).collect(),
    }
}

/// G4 A1 (spec 5): the first private declaration reachable from the nominal `names` (identities): the names themselves,
/// then, transitively, the field / payload types of every public declaration reached. `seen` is the visited set shared by
/// the whole program (cycles terminate). Returns (private identity, via) where via is the chain "P.field -> Q.g" leading to
/// it ("" for a direct mention).
fn private_in(types: &HashMap<String, TyIface>, names: &[String], seen: &mut HashSet<String>) -> Option<(String, String)> {
    for n in names {
        let d = match types.get(n) {
            Some(d) => d,
            None => continue,
        };
        if !d.is_pub {
            return Some((n.clone(), String::new()));
        }
        if seen.contains(n) {
            continue;
        }
        seen.insert(n.clone());
        for (fname, fty) in &d.fields {
            if let Some((p, via)) = private_in(types, &dependencies(fty), seen) {
                let chain = if via.is_empty() { format!("{}.{}", n, fname) } else { format!("{}.{} -> {}", n, fname, via) };
                return Some((p, chain));
            }
        }
    }
    None
}

fn leak(line: i64, col: i64, is_fn: bool, item_name: &str, r: (String, String), what: &str) -> PruvError {
    let (n, via) = r;
    err(
        line,
        col,
        "public_interface",
        format!(
            "public {} {} exposes the private type {} in its {}{}",
            if is_fn { "function" } else { "type" },
            item_name,
            n,
            what,
            if via.is_empty() { String::new() } else { format!(" (through {})", via) }
        ),
        format!("make {} `pub`, or keep {} private", n, item_name),
    )
}

#[allow(clippy::too_many_arguments)]
fn iface_type(
    types: &HashMap<String, TyIface>,
    ty: &GType,
    line: i64,
    col: i64,
    is_fn: bool,
    item_name: &str,
    what: &str,
    seen: &mut HashSet<String>,
) -> Res<()> {
    if let Some(r) = private_in(types, &dependencies(ty), seen) {
        return Err(leak(line, col, is_fn, item_name, r, what));
    }
    Ok(())
}

/// the expression children in the order of refine.py `_kids`
fn kids(e: &Expr) -> Vec<&Expr> {
    match e {
        Expr::Spent(_) => Vec::new(),
        Expr::Unary(x) => vec![&*x.operand],
        Expr::Binary(x) => vec![&*x.left, &*x.right],
        Expr::Index(x) => vec![&*x.array, &*x.index],
        Expr::Ctor(x) => x.arg.iter().map(|a| &**a).collect(),
        Expr::Quant(x) => vec![&*x.lo, &*x.hi, &*x.body],
        Expr::Call(x) => x.args.iter().collect(),
        Expr::StructLit(x) => x.fields.iter().map(|f| &f.value).collect(),
        Expr::EnumCtor(x) => x.args.iter().collect(),
        Expr::FieldAccess(x) => vec![&*x.base],
        Expr::IsVariant(x) => vec![&*x.value],
        Expr::VariantField(x) => vec![&*x.value],
        _ => Vec::new(),
    }
}

/// full syntax of a contract expression, unreachable short-circuit operands included
fn iface_expr(types: &HashMap<String, TyIface>, e: &Expr, item_name: &str, seen: &mut HashSet<String>) -> Res<()> {
    let (line, col) = (e.line(), e.col());
    let name: Option<&String> = match e {
        Expr::StructLit(x) => Some(&x.name),
        Expr::EnumCtor(x) => Some(&x.enum_name),
        Expr::IsVariant(x) => Some(&x.enum_name),
        Expr::VariantField(x) => Some(&x.enum_name),
        _ => None,
    };
    if let Some(n) = name {
        if let Some(r) = private_in(types, std::slice::from_ref(n), seen) {
            return Err(leak(line, col, true, item_name, r, "contract"));
        }
    }
    let targs: Option<&Vec<GType>> = match e {
        Expr::Call(x) => x.targs.as_ref(),
        Expr::StructLit(x) => x.targs.as_ref(),
        Expr::EnumCtor(x) => x.targs.as_ref(),
        Expr::Ctor(x) => x.targs.as_ref(),
        _ => None,
    };
    if let Some(ts) = targs {
        for t in ts {
            iface_type(types, t, line, col, true, item_name, "contract", seen)?;
        }
    }
    for k in kids(e) {
        iface_expr(types, k, item_name, seen)?;
    }
    Ok(())
}

fn iface_fn(types: &HashMap<String, TyIface>, f: &Function, seen: &mut HashSet<String>) -> Res<()> {
    for p in &f.params {
        iface_type(types, &GType::from_key(&p.ty), f.line, f.col, true, &f.name, "signature", seen)?;
    }
    iface_type(types, &GType::from_key(&f.ret), f.line, f.col, true, &f.name, "signature", seen)?;
    for e in f.requires.iter().chain(f.ensures.iter()).chain(f.decreases.iter()).chain(f.cost.iter()) {
        iface_expr(types, e, &f.name, seen)?;
    }
    Ok(())
}

fn iface_ty(types: &HashMap<String, TyIface>, d: &TypeDecl, seen: &mut HashSet<String>) -> Res<()> {
    for fd in decl_fields(d) {
        iface_type(types, &GType::from_key(&fd.ty), fd.line, fd.col, false, d.name(), &format!("field {}", fd.name), seen)?;
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// entries
// ---------------------------------------------------------------------------

fn entries(prog: &Program, g4: &mut G4) -> Res<()> {
    let mut out: Vec<String> = Vec::new();
    for (i, f) in prog.functions.iter().enumerate() {
        let meta_module = g4.fn_meta[i].module;
        if !g4.modules[meta_module].path.is_empty() {
            continue;
        }
        if g4.fn_meta[i].src_name == "main" {
            if !g4.fn_meta[i].is_pub {
                return Err(err(f.line, f.col, "entry_main", "the root main must be `pub fn main() -> ()`", "write `pub fn main() -> () { .. }`"));
            }
            if !f.tparams.is_empty() {
                return Err(err(
                    f.line,
                    f.col,
                    "entry_main",
                    "the root main cannot declare type parameters",
                    "make main a plain function; call generic functions from it with explicit type arguments",
                ));
            }
            if !f.params.is_empty() {
                return Err(err(f.line, f.col, "entry_main", "the root main takes no parameters", "remove the parameters of main"));
            }
            if f.ret != "unit" {
                return Err(err(f.line, f.col, "entry_main", "the root main must return ()", "write `pub fn main() -> ()`"));
            }
            g4.main = Some(f.name.clone());
        }
        if g4.fn_meta[i].is_pub && f.tparams.is_empty() && f.foreign.is_none() {
            g4.fn_meta[i].host_entry = true;
            out.push(f.name.clone());
        }
    }
    g4.entries = out;
    Ok(())
}
