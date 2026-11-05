# PCBRouteAgent article figures

The bilingual article sources are in `content/posts/pcbrouteagent/en.md` and `zh.md`.

Current figures, shared by both language versions:

- `task.png`: rendered at 2400 px from the paper's `arxiv/fig/pcb-routing-task.pdf`.
- `framework.png`: copied from the paper's current `arxiv/fig/example.png`.
  This is the preliminary framework illustration; replace it when the revised artwork is ready.
- Case study remains reserved: replace each `.case-image-space` and its accompanying text
  with actual observations.

Store the finished images in this directory. Use root-relative paths such as
`/assets/research/pcbrouteagent/task.png` in both language versions. Replacing
`framework.png` updates both articles; update the image width and height attributes
in the Markdown if the dimensions change. Supply
descriptive alt text and update the captions. Do not present the placeholder
case descriptions as measured case-study findings.

Run `python3 build.py` from the repository root after editing.
