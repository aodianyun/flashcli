fn main() {
    #[cfg(windows)]
    {
        let mut res = winres::WindowsResource::new();
        res.set_icon("build/icon.ico");
        res.set("ProductName", "FlashServer");
        res.set("FileDescription", "FlashServer Desktop");
        res.set("CompanyName", "FlashHub");
        res.compile().expect("winres failed");
    }
}
