//! 사용자 struct/enum 타입 정보(typeinfo.py 대응).
//! `type_name` 은 모든 타입의 소스 철자를, `TypeTable` 은 검사된 프로그램의 선언을 색인한다.

use crate::ast::*;
use std::collections::{HashMap, HashSet};

pub const BUILTIN_TYPE_NAMES: [&str; 6] = ["i64", "bool", "unit", "array", "option", "result"];

/// 내장이 아닌 이름이면 사용자 타입(선언 여부와 무관).
pub fn is_user_type(ty: &str) -> bool {
    !BUILTIN_TYPE_NAMES.contains(&ty)
}

/// 소스 수준 철자. 사용자 타입은 자기 이름 그대로.
pub fn type_name(ty: &str) -> String {
    match ty {
        "i64" => "i64".to_string(),
        "bool" => "bool".to_string(),
        "unit" => "()".to_string(),
        "array" => "[i64]".to_string(),
        "option" => "Option<i64>".to_string(),
        "result" => "Result<i64>".to_string(),
        other => other.to_string(),
    }
}

impl TypeDecl {
    pub fn name(&self) -> &str {
        match self {
            TypeDecl::Struct(s) => &s.name,
            TypeDecl::Enum(e) => &e.name,
        }
    }
    pub fn line(&self) -> i64 {
        match self {
            TypeDecl::Struct(s) => s.line,
            TypeDecl::Enum(e) => e.line,
        }
    }
    pub fn col(&self) -> i64 {
        match self {
            TypeDecl::Struct(s) => s.col,
            TypeDecl::Enum(e) => e.col,
        }
    }
    /// 구조체는 필드, enum 은 모든 변형의 필드를 선언 순서로.
    pub fn all_fields(&self) -> Vec<&FieldDecl> {
        match self {
            TypeDecl::Struct(s) => s.fields.iter().collect(),
            TypeDecl::Enum(e) => e.variants.iter().flat_map(|v| v.fields.iter()).collect(),
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct TypeTable {
    /// 선언 순서(첫 선언 우선, 이름 중복 없음).
    pub decls: Vec<TypeDecl>,
    index: HashMap<String, usize>,
    /// 의존 먼저·선언 안정 순서: `decls` 의 인덱스.
    pub order: Vec<usize>,
}

impl TypeTable {
    pub fn new(types: &[TypeDecl]) -> TypeTable {
        let mut t = TypeTable::default();
        for d in types {
            if !t.index.contains_key(d.name()) {
                t.index.insert(d.name().to_string(), t.decls.len());
                t.decls.push(d.clone());
            }
        }
        t.build_order();
        t
    }

    /// 의존 순서로 나열한 선언.
    pub fn ordered(&self) -> impl Iterator<Item = &TypeDecl> {
        self.order.iter().map(move |&i| &self.decls[i])
    }

    /// 필드 순서대로, 중복 없이, 선언된 이름만.
    pub fn deps(&self, d: &TypeDecl) -> Vec<String> {
        let mut out: Vec<String> = Vec::new();
        for f in d.all_fields() {
            if is_user_type(&f.ty) && self.index.contains_key(&f.ty) && !out.contains(&f.ty) {
                out.push(f.ty.clone());
            }
        }
        out
    }

    fn build_order(&mut self) {
        let mut seen: HashSet<usize> = HashSet::new();
        let mut order: Vec<usize> = Vec::new();
        for i in 0..self.decls.len() {
            self.visit(i, &mut seen, &mut order);
        }
        self.order = order;
    }

    fn visit(&self, i: usize, seen: &mut HashSet<usize>, order: &mut Vec<usize>) {
        if !seen.insert(i) {
            return; // 먼저 표시: 순환(검사기가 거부)이 있어도 무한 반복 없음
        }
        for n in self.deps(&self.decls[i]) {
            if let Some(&j) = self.index.get(&n) {
                self.visit(j, seen, order);
            }
        }
        order.push(i);
    }

    // ---- 조회 ----
    pub fn decl(&self, ty: &str) -> Option<&TypeDecl> {
        self.index.get(ty).map(|&i| &self.decls[i])
    }

    pub fn is_struct(&self, ty: &str) -> bool {
        matches!(self.decl(ty), Some(TypeDecl::Struct(_))) && is_user_type(ty)
    }

    pub fn is_enum(&self, ty: &str) -> bool {
        matches!(self.decl(ty), Some(TypeDecl::Enum(_))) && is_user_type(ty)
    }

    /// enum 의 변형(없거나 enum 이 아니면 None).
    pub fn variant(&self, ty: &str, variant: &str) -> Option<&VariantDecl> {
        match self.decl(ty) {
            Some(TypeDecl::Enum(e)) => e.variants.iter().find(|v| v.name == variant),
            _ => None,
        }
    }

    /// struct 필드, 또는 enum 의 `variant` 필드(선언 순서). 찾지 못하면 None.
    pub fn fields(&self, ty: &str, variant: Option<&str>) -> Option<&[FieldDecl]> {
        match self.decl(ty)? {
            TypeDecl::Struct(s) => Some(&s.fields),
            TypeDecl::Enum(_) => self.variant(ty, variant?).map(|v| v.fields.as_slice()),
        }
    }

    pub fn field_index(&self, ty: &str, name: &str, variant: Option<&str>) -> Option<usize> {
        self.fields(ty, variant)?.iter().position(|f| f.name == name)
    }

    pub fn variant_index(&self, ty: &str, variant: &str) -> Option<usize> {
        match self.decl(ty) {
            Some(TypeDecl::Enum(e)) => e.variants.iter().position(|v| v.name == variant),
            _ => None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn names() {
        assert_eq!(type_name("unit"), "()");
        assert_eq!(type_name("array"), "[i64]");
        assert_eq!(type_name("option"), "Option<i64>");
        assert_eq!(type_name("result"), "Result<i64>");
        assert_eq!(type_name("Point"), "Point");
        assert!(is_user_type("Point"));
        assert!(!is_user_type("i64"));
    }
}
