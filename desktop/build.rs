fn main() {
    #[cfg(windows)]
    {
        let mut res = winres::WindowsResource::new();
        res.set_icon("build/icon.ico");
        res.set("ProductName", "flashcli-desktop");
        res.set("FileDescription", "flashcli desktop");
        res.set("CompanyName", "FlashHub");
        res.compile().expect("winres failed");
    }
}
