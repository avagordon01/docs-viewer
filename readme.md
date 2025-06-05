# docs viewer

terminal documentation viewer with live / interactive fuzzy search

## how it works

- download docsets (approximately standard apple/xcode format for documentation bundles, basically tree of HTML, and sqlite index)
- fuzzy search them with sqlite full-text-search trigram index
- present the results interactively using [textual](https://textual.textualize.io/)
- present the docs themselves in the terminal by converting the HTML to markdown and then using [textual markdown widget](https://textual.textualize.io/widgets/markdown/)
