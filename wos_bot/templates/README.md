# Templates

One folder per screen, created with `python tools/capture.py crop --screen <folder>`:

```
templates/
  city/          anchors and buttons on the main city screen
  popups/        close buttons and other popup elements
  ...
```

Each `<name>.png` is a full-resolution crop from a 720x1280 screenshot. Its `<name>.json` sidecar
records where it was cropped (`region: [x, y, w, h]`) and the source screenshot. Vision (step 2)
uses the region to narrow the search area and as a fallback tap position, so recrop with the tool
instead of editing a PNG by hand.

The exact list of templates needed comes in step 2.
