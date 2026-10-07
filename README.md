# AetherRoute

**Your routes, in view.** A free, open-source Windows overlay for resource
routes on Aion 2's big map and minimap.

## Install

Download **AetherRoute-Setup-<version>.exe** from this repository's published
GitHub Releases and run it. Open **AetherRoute** from the Start menu. Python
is included. For the portable build, extract the entire Windows ZIP and
run **AetherRoute.exe** with its supporting files alongside it.

This download is a **source release candidate**, with the Windows installer
build workflow included. To run this source on Windows, install 64-bit
Python 3.11–3.14 with tkinter, extract the ZIP and double-click **START.cmd**.
The first setup installs pinned, hash-checked dependencies.

## Create a route

1. Click the small **AetherRoute** launcher at the bottom-right of your screen.
2. Click **Interactive maps** and choose **Altgard** or **Verteron**. Their maps,
   resource databases and bounds are already included; no website setup is needed.
3. Choose resource types and a region, or select **Drag to select an area**.
4. Click resources in visit order, or leave the route empty to plan it later.
5. Click **Create zone + edit route** and name your zone. Click resource symbols
   to add stops with their exact type. Small areas enlarge to fit the editor.
6. In **Overlay**, click **Bind game**, switch to Aion 2 within three seconds,
   then press **M**. Wait for terrain alignment.

Use Windowed or Borderless mode. **Hide to launcher** hides the main window;
click the launcher to reopen it. Closing the main window also hides it.
Use **Quit** to exit. You can drag the launcher; right-click to reset it.
After binding, the launcher follows the game window and appears while that
game is focused. Before binding, it appears on the desktop.
If the game closes, the launcher returns to the desktop so you can bind again.

For the minimap, use **Set minimap area**, select its terrain interior, and
choose **Minimap / floating map**. Leave **Hide while big map moves** checked
if dragging causes lag. Shortcuts: Ctrl+Alt+N/P for next/previous stop,
Ctrl+Alt+Space to pause. Shortcuts act while the bound game is focused.

## Use your own picture instead

**New zone / picture** is a separate workflow. Choose a saved map picture,
name it and use the whole image or select a crop. In the editor, choose
**Type** and click to place a stop. Picture zones and interactive map zones
have separate saved-zone lists; creating either keeps your existing zones.

To capture a picture, open the [Questlog Aion 2 map](https://questlog.gg/aion-2/en/map),
choose your zone and filters, move the cursor away from popups, then press
**Windows+Shift+S**. Capture only the map and save it as PNG.

**Settings → Developer mode** reveals custom map/database imports, bounds,
custom catalogs and icon teaching/import. Existing custom worlds and saved
zones remain available when Developer mode is off. Previously learned picture
icons still type automatically. See [MAP-PACKS.txt](MAP-PACKS.txt).

## Save, share and plan

Changes save automatically. **New route** keeps the current route.
**Delete route** and **Delete zone** each ask twice. Export a **profile** to
share the zone picture and routes together; route-only exports require the
same reference picture on both computers.

In **Model planning**, use **Draw path from image**, select resource types,
and **Export model pack (image + JSON)**. Give `map.png`, `legend.png`,
`task.json` and the instructions in `PROMPT.txt` to your own image-capable
model. The picture includes selected catalog resources even without a route.
Import its JSON response as a new editable route. Review paths for cliffs,
rivers and access. No model account or API key is needed by AetherRoute.

See [the simple guide](README.txt) for detailed controls and troubleshooting.

## Preferences and privacy

Settings control the launcher, starting collapsed, keeping the main window
above the game, and Developer mode. Saved data stays in
`%LOCALAPPDATA%\Aion2RouteSync` to preserve upgrades from Wayveil.
Existing profiles and compatible map packs remain supported.

Tracking and planning exports run locally. There are no ads, sponsor panel,
telemetry or automatic model connections. **Buy me a coffee** opens the
optional [Ko-fi support page](https://ko-fi.com/juiceoverload) in your browser.
There is no embedded payment panel. Profile sharing omits model prompts,
application preferences and hidden image metadata; visible images and names
are shared. See [SECURITY.txt](SECURITY.txt).

## Build and release

The [Windows workflow](.github/workflows/windows.yml) builds and smoke-tests
an installer, portable ZIP and clean source ZIP. A tag matching
`product.VERSION` creates a draft prerelease for review. For a manual build,
install Inno Setup 6 and run **BUILD.cmd** on Windows. See [RELEASE.txt](RELEASE.txt).

Run `python -m unittest discover -s tests -v`. The frozen executable's
`--self-test` checks bundled worlds, imports and temporary profile round trips.
Live game focus, overlay tracking and monitor/DPI behavior need a Windows
check before publishing. Builds are unsigned unless you add signing.

## License and support

Application code is [MIT](LICENSE.txt). Dependency notices are included.
Bundled Aion 2 map artwork and supplied resource data retain their original
rights; see [NOTICE.txt](NOTICE.txt) and [maps/NOTICE.txt](maps/NOTICE.txt).
AetherRoute is an independent project, formerly named Wayveil.

[Buy me a coffee on Ko-fi](https://ko-fi.com/juiceoverload)
