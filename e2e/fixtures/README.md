# Test photos

Real photos for the end-to-end tests that run the real vision model (`tests/ai.spec.ts`). Both are from Wikimedia Commons, downscaled to at most 1024 px on the long side and re-encoded as JPEG (quality 85); nothing else was changed.

| File | Source | Author | Licence |
|---|---|---|---|
| `pothole-villeray.jpg` | [Pothole in Villeray, Montréal](https://commons.wikimedia.org/wiki/File:Pothole_in_Villeray,_Montr%C3%A9al.jpg) (2007) | Miguel Tremblay | Public domain |
| `pothole-monaghan.jpg` | [Pothole on local Road in County Monaghan](https://commons.wikimedia.org/wiki/File:Pothole_on_local_Road_in_County_Monaghan.jpg) (2020) | Computerfan0 | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |

Both are also in the evaluation set (`apps/api/scripts/eval/manifest.csv`), where the shipped model classifies them as potholes. Neither has a person in it, so face blurring leaves them alone.
