fn main() {

    std::fs::write("bounds.bin", [255u8]).unwrap();
    sol::past_end("bounds.bin");
}
