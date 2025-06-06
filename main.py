import argparse
import shutil
import sqlite3
import tarfile
import tomllib
from pathlib import Path
from typing import List

import requests
from html_to_markdown import convert_to_markdown
from textual.app import App, Binding, ComposeResult
from textual.widgets import Input, Markdown, OptionList
from xdg_base_dirs import xdg_config_home, xdg_data_home


class DocSet:
    def __init__(self, docset: str):
        self.data_dir = xdg_data_home() / "docs-viewer/docsets"
        self.dbfile = (
            self.data_dir / f"{docset}/{docset}.docset/Contents/Resources/docSet.dsidx"
        )
        self.db = sqlite3.connect(self.dbfile)

    def get_all_tokens(self) -> List[tuple[int, int]]:
        cur = self.db.cursor()
        res = cur.execute(
            "select z_pk, zmetainformation, ztokenname from ztoken limit 20"
        )
        return res.fetchall()

    def get_all_paths(self) -> List[tuple[int, int]]:
        cur = self.db.cursor()
        res = cur.execute("select z_pk, zpath from zfilepath")
        return res.fetchall()

    def search(self, search_str: str) -> List[tuple[str, Path]]:
        # TODO
        cur = self.db.cursor()
        res = cur.execute(
            f"""
            select *, -length(name) as score
            from search_index_view
            where name like "%{search_str}%"
        """
        )
        return res.fetchall()

    def create_index(self) -> None:
        cur = self.db.cursor()
        cur.execute("""
            create view if not exists search_index_view as
            select
                ztoken.ztokenname as name,
                ztokentype.ztypename as type,
                zfilepath.zpath as path,
                ztokenmetainformation.zanchor as anchor
            from ztoken
            inner join ztokenmetainformation
                on ztoken.zmetainformation = ztokenmetainformation.z_pk
            inner join zfilepath
                on ztokenmetainformation.zfile = zfilepath.z_pk
            inner join ztokentype
                on ztoken.ztokentype = ztokentype.z_pk
            order by -length(name)
        """)


class DocsViewer(App):
    CSS = """
    Screen {
        layout: horizontal;
    }
    * {
        border: none;
        padding: 0;
        margin: 0;
        box-sizing: content-box;
    }
    OptionList {
        height: 100%;
        width: 30%;
    }
    Markdown {
        height: 100%;
    }
    Input {
        dock: bottom;
        height: 1;
    }
    """
    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
        Binding("escape", "quit", "Quit", show=False, priority=True),
        Binding("enter", "open()", "open", show=False, priority=True),
    ]

    def set_ds(self, ds: DocSet):
        self.ds = ds

    def compose(self) -> ComposeResult:
        yield OptionList()
        yield Markdown()
        yield Input(placeholder="search")

    def on_ready(self) -> None:
        self.query_one(Input).focus()
        # TODO move bindings to top-level

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        highlighted = event.option.prompt
        # TODO render markdown file
        md = self.query_one(Markdown)
        md.update(highlighted)

    def on_input_changed(self, event: Input.Changed) -> None:
        search_str = event.value
        results = [name for (name, _, _, _, _) in self.ds.search(search_str)]
        ol = self.query_one(OptionList)
        ol.clear_options()
        ol.add_options(results)
        ol.action_last()

    def action_open(self) -> None:
        ol = self.query_one(OptionList)
        chosen_value = ol.get_option_at_index(ol.highlighted).id
        md = self.query_one(Markdown)
        md.update(chosen_value)


def download_file(url: str, dir: Path) -> Path:
    local_filename = dir / url.split("/")[-1]
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(local_filename, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    return local_filename


def extract_tgz(file: Path) -> Path:
    tar = tarfile.open(file, "r:gz")
    dir = Path(file.with_suffix(""))
    shutil.rmtree(dir, ignore_errors=True)
    dir.mkdir(parents=True)
    tar.extractall(path=dir, filter="data")
    tar.close()
    return dir


def download_docsets(download_all: bool = False) -> None:
    config_file = xdg_config_home() / "docs-viewer/config.toml"
    with open(config_file, "rb") as file:
        config = tomllib.load(file)
    docsets = config["docsets"]
    data_dir = xdg_data_home() / "docs-viewer/docsets"
    if not data_dir.exists():
        data_dir.mkdir(parents=True)
    for docset in docsets:
        if not (data_dir / docset).exists() or download_all:
            file = download_file(f"https://kapeli.com/feeds/{docset}.tgz", data_dir)
            extract_tgz(file)


def open_as_markdown(filename: str) -> str:
    with open(filename) as file:
        return convert_to_markdown(file.read())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-new", action="store_true")
    parser.add_argument("--download-all", action="store_true")
    args = parser.parse_args()
    if args.download_new:
        download_docsets(args.download_all)
        exit()
    ds = DocSet("C++")
    ds.create_index()
    app = DocsViewer()
    app.set_ds(ds)
    app.run()
