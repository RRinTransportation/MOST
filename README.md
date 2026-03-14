# MOST
Webpage for Measuring Open Science in Transportation Research

## GitHub Pages Hosting

This repository hosts HTML files that are accessible via GitHub Pages at:
```
https://RRinTransportation.github.io/OTSM/{HTML file name}
```

## Local Testing

To test HTML files locally, you can:
- Open the HTML files directly in your browser
- Use a simple HTTP server (e.g., `python -m http.server 8000`)

## Repository Structure

```
OTSM/
├── index.html          # Main landing page
├── explorer.html        # Example additional page
├── README.md           # This file
└── .gitignore          # Git ignore rules

## Blog

The blog is generated from markdown files in `blog/posts/`. To update the blog:

1. Add a new markdown file to `blog/posts/`.
2. Run `python build_blog.py` to compile the markdown files to HTML.
3. The generated HTML files will be in `blog/` and the main blog index will be at `blog/index.html`.

Dependencies:
- `markdown`
- `jinja2`

To install dependencies:
```bash
pip install markdown jinja2
```
```
