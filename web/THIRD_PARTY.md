# Browser dependencies

The static site serves these unmodified libraries locally. No runtime CDN or
analytics service is used.

OpenCV's Emscripten bindings generate functions at runtime. The site's script
policy permits this (`unsafe-eval`) while restricting scripts, connections, and
workers to the site's own origin and blocking inline scripts.

| Library | Version | Upstream | License |
| --- | --- | --- | --- |
| OpenCV.js | 4.12.0 | https://docs.opencv.org/4.12.0/opencv.js | Apache-2.0, `vendor/OPENCV-LICENSE` |
| Mediabunny | 1.66.4 | https://www.npmjs.com/package/mediabunny/v/1.66.4 | MPL-2.0, `vendor/MEDIABUNNY-LICENSE` |

Mediabunny's source is available at
https://github.com/Vanilagy/mediabunny/tree/v1.66.4.
OpenCV's source is available at https://github.com/opencv/opencv/tree/4.12.0.
The project MIT license covers SteadyFrame's own code; dependency licenses remain
in effect for the bundled libraries.

Demo media credits and benchmark provenance are in
[`docs/MEDIA.md`](https://github.com/varunmenon0/SteadyFrame/blob/main/docs/MEDIA.md).
`media/sample-input.mp4` is a silent six-second, 960 × 540 excerpt of the same
CC0 fox footage credited there, re-encoded as H.264 for the interactive sample.
The poster images are frames from their respective comparisons.
