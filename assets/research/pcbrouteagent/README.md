# PCBRouteAgent article figures

The bilingual article sources are in `content/posts/pcbrouteagent/en.md` and `zh.md`.

Reserved figure locations:

- Task: replace the first `<div class="figure-space">...</div>` with the task image.
- Method: replace the second `<div class="figure-space">...</div>` with the architecture image.
- Case study: replace each `.case-image-space` and its accompanying text with actual observations.

Store the finished images in this directory. Use root-relative paths such as
`/assets/research/pcbrouteagent/task.png` in both language versions. Supply
descriptive alt text and update the captions. Do not present the placeholder
case descriptions as measured case-study findings.

Run `python3 build.py` from the repository root after editing.
