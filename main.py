import argparse
import shutil
import sqlite3
import subprocess
import tarfile
import tomllib
import urllib.parse
from pathlib import Path
from typing import List

import requests
from bs4 import BeautifulSoup
from html_to_markdown import convert_to_markdown
from readabilipy import simple_tree_from_html_string
from textual.app import App, Binding, ComposeResult
from textual.widgets import Input, Markdown, OptionList
from xdg_base_dirs import xdg_config_home, xdg_data_home

data_dir = xdg_data_home() / "docs-viewer/docsets"
config_file = xdg_config_home() / "docs-viewer/config.toml"


class DocSet:
    def __init__(self, docset: str):
        self.docset_dir = data_dir / f"{docset}/{docset}.docset/Contents/Resources"
        self.dbfile = data_dir / f"{self.docset_dir}/docSet.dsidx"
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

    def process_path(self, path: str) -> tuple[str, str]:
        path = path[path.rfind(">") + 1 :]
        path = urllib.parse.unquote(path)
        url = f"https://{path}"
        path = f"{self.docset_dir}/Documents/{path}"
        return (path, url)

    def search(self, search_str: str) -> List[tuple[str, Path]]:
        # TODO better search function
        # sqlite fts5 trigrams?
        cur = self.db.cursor()
        res = cur.execute(
            f"""
            select *, -length(name) as score
            from search_index_view
            where name like "%{search_str}%"
        """
        )
        return [
            (name, *self.process_path(path)) for (name, _, path, _, _) in res.fetchall()
        ]

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
        Binding("escape", "quit", "Quit", show=False, priority=True),
        Binding("enter", "open()", "open", show=False, priority=True),
        Binding("up", "up()", "up", show=False, priority=True),
        Binding("down", "down()", "down", show=False, priority=True),
    ]

    def set_ds(self, ds: DocSet):
        self.ds = ds

    def compose(self) -> ComposeResult:
        yield Input(placeholder="search")
        yield OptionList()
        yield Markdown()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        highlighted = event.option.prompt
        path, _ = self.options[highlighted]
        markdown = open_as_markdown(path)
        md = self.query_one(Markdown)
        md.update(markdown)

    def on_input_changed(self, event: Input.Changed) -> None:
        search_str = event.value
        results = {
            name: (path, url) for (name, path, url) in self.ds.search(search_str)
        }
        self.options = results
        ol = self.query_one(OptionList)
        ol.clear_options()
        ol.add_options(results.keys())
        ol.action_last()

    def action_up(self) -> None:
        ol = self.query_one(OptionList)
        ol.action_cursor_up()

    def action_down(self) -> None:
        ol = self.query_one(OptionList)
        ol.action_cursor_down()

    def action_open(self) -> None:
        ol = self.query_one(OptionList)
        highlighted = ol.get_option_at_index(ol.highlighted).prompt
        _, url = self.options[highlighted]
        subprocess.run(["xdg-open", url])


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
    with open(config_file, "rb") as file:
        config = tomllib.load(file)
    docsets = config["docsets"]
    if not data_dir.exists():
        data_dir.mkdir(parents=True)
    for docset in docsets:
        if not (data_dir / docset).exists() or download_all:
            file = download_file(f"https://kapeli.com/feeds/{docset}.tgz", data_dir)
            extract_tgz(file)


def open_as_markdown(filename: str) -> str:
    # TODO this is also a little bit slow, offline we could convert all .html to .md
    # TODO this HTML -> markdown conversion looks like garbage
    # - doesn't strip "display: none" elements
    # - large code blocks have vertical scroll for no reason
    # - extra [[edit]](...) cruft everywhere
    # maybe a textual HTML widget would be better
    # TODO maybe use https://github.com/alan-turing-institute/ReadabiliPy
    with open(filename) as file:
        html = file.read()
        html_simple_parsed = simple_tree_from_html_string(html)
        html_parsed = BeautifulSoup(html, "html.parser")
        delete_selectors = [
            'div[class*="nav"]',
            'div[class="noprint"]',
        ]
        for delete_selector in delete_selectors:
            for tag in html_parsed.css.select(delete_selector):
                print("removing tag!")
                tag.decompose()
        html_simple = str(html_parsed)
        markdown = convert_to_markdown(html_simple)
        return markdown


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-new", action="store_true")
    parser.add_argument("--download-all", action="store_true")
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    if args.test:
        print(
            open_as_markdown(
                "/home/ava/.local/share/docs-viewer/docsets/C++/C++.docset/Contents/Resources/Documents/en.cppreference.com/w/cpp/container/vector_bool.html"
            )
        )
        exit()
    if args.download_new:
        download_docsets(args.download_all)
        exit()
    ds = DocSet("C++")
    ds.create_index()
    app = DocsViewer()
    app.set_ds(ds)
    app.run()
