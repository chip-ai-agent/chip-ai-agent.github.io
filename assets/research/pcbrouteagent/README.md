# PCBRouteAgent article figures

The bilingual article sources are in `content/posts/pcbrouteagent/en.md` and `zh.md`.

Current figures, shared by both language versions:

- `task.png`: rendered at 2400 px from the paper's `arxiv/fig/pcb-routing-task.pdf`.
- `framework.png`: rendered at 2600 px after trimming PDF page margins from the paper's `arxiv/fig/method.pdf`
  (Overleaf revision `3c60615`). The figure URLs include the source revision to refresh browser caches.

Store the finished images in this directory. Use root-relative paths such as
`/assets/research/pcbrouteagent/task.png` in both language versions. Replacing
`framework.png` updates both articles; update the image width and height attributes
in the Markdown if the dimensions change. Supply
descriptive alt text and update the captions.

Run `python3 build.py` from the repository root after editing.
