Releases are now driven by `CHANGELOG.md` instead of by a hand-cut git tag.
Contributors add a [towncrier](https://towncrier.readthedocs.io/) news fragment
under `news/` (`make news NAME=1234.feature.md`), the *Dispatch release*
workflow materializes the pending fragments into a version section, and merging
that pull request publishes: the release matrix builds every wheel, the sdist
and the runtime-verified PyEmscripten wheel, a human approves the single
credentialed upload job, and only a successful upload creates the tag and the
GitHub release. `CHANGELOG.md` is generated from that point on — version
headings are no longer written by hand.
