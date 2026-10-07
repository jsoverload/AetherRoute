AETHERROUTE — SIMPLE GUIDE

1. OPEN THE TOOL

On Windows, open AetherRoute from the Start menu or run AetherRoute.exe.
For this source ZIP, install 64-bit Python 3.11–3.14 with tkinter, extract
EVERYTHING, then double-click START.cmd. First setup needs the internet.
Installers and portable ZIPs are at:
https://github.com/jsoverload/AetherRoute/releases

A small AetherRoute button appears at the bottom-right. Click it to open
the main window. Hide to launcher, or the window's X, returns to that button.
Quit exits the tool. Drag the button to move it; right-click for reset,
settings or Quit. Use Windowed or Borderless mode in Aion 2.

2. CREATE A ZONE FROM AN INCLUDED MAP — RECOMMENDED

1) Click Interactive maps.
2) Choose Altgard or Verteron. Images, resources and map bounds are included.
3) Choose resources such as Gems and Od. Search for an item if needed.
4) Choose a named Region, or select Drag to select an area and drag a box.
   Mouse wheel zooms. In Pan / click route stops, drag to move the map.
5) Click resource symbols in the order you want to visit them. You can also
   leave the route empty and create it in the editor or with your own model.
6) Click Create zone + edit route and give the zone a name.

The route editor uses the same terrain and symbols. Clicking a database
resource gives it the exact resource type and name automatically. Gems are
purple diamonds; Od is a green star; Ore is a square; cubes have a C.
Small crops enlarge for editing. Coordinates and the tracking image stay
at their original size.

3. CREATE A ZONE FROM YOUR OWN PICTURE — ALTERNATIVE

1) Open https://questlog.gg/aion-2/en/map in your browser.
2) Choose the world and show only the resources you want.
3) Zoom until the resource icons and terrain are clear. Keep roads, rivers
   and landmarks visible. Move the pointer away so no popup covers the map.
4) Press Windows + Shift + S. Capture only the map, leaving out browser
   controls, side menus and account details. Save the picture as a PNG.
5) In AetherRoute, click New zone / picture and choose that PNG.
6) Name the zone. Choose Use whole image or drag a crop and use it.
7) In Edit route, choose Type, then click to place each route stop.

Picture zones and Interactive map zones have separate saved-zone lists.
Pick the group, then a saved zone. The Active zone line shows which one
is currently in use. Creating a zone keeps every previous profile.
A picture by itself does not provide a database of resource locations.

4. EDIT AND SAVE ROUTES

- Connect all nodes: add all catalog resources matching the selected types
  in this zone. Existing stops keep their order; new resources are added in
  nearby order without duplicates. Undo reverses the whole action. Find
  this button in Routes or Edit route. Choose fewer types or a smaller zone
  if the route would exceed 1,000 stops; no partial route is added.
- Click a stop: select it; choose Type/name and Apply to selected to change it.
- Ctrl + click: add a manual stop using your chosen Type/name.
- Right-click a stop: remove it.
- Shift + click a stop: make it the starting stop.
- Move up / Move down: change visit order. Undo reverses an edit.
- Loop: connect the last stop to the first.
- Calculate shortest: shorten map distance; review travel barriers yourself.

Name the route in the main window. Changes save automatically. New route
keeps the current route. Delete route and Delete zone ask you to confirm
twice. Export a profile first if you want a portable backup.

5. SHOW THE ROUTE ON THE GAME'S BIG MAP

1) Select the correct saved zone and route.
2) In Overlay, set Track this map to Big map.
3) Click Bind game, then switch to Aion 2 within three seconds.
4) Press M and view the matching area in your game map.
5) Wait for terrain alignment. The route appears when alignment is confirmed.
6) Use Hide to launcher to return to the game. Click the small button to edit.

The launcher follows the bound game's bottom-right corner. It hides when
another program is focused. While unbound, it sits on your desktop.
When the game closes, it returns to the desktop so you can reopen and bind again.
Keep Hide while big map moves checked if dragging causes tracking gaps.
The route hides while the map moves, then returns when the map settles.

Next node / Ctrl + Alt + N advances a stop. Ctrl + Alt + P goes back.
Ctrl + Alt + Space pauses/resumes tracking. These shortcuts act while the
bound game is focused.

6. USE THE MINIMAP OR FLOATING MAP

1) Bind the game and show its minimap or floating map panel.
2) Click Set minimap area and switch back to the game within three seconds.
3) In the captured picture, select the map terrain only; omit its controls.
4) Choose Rectangle for a rectangular panel or Round for a circular map.
5) Click Use this map area. The tool switches to Minimap / floating map.

Use high in-game map opacity. Re-select the area if you move or resize the
panel. Settings save with the zone. Only the current stop is labeled in
minimap mode. Switch Track this map back to Big map for the full map.

7. SHARE OR IMPORT

Export profile shares the zone picture, resources and saved routes together.
Import profile adds another user's zone without replacing your zones.
Export route / Import route shares one route; both users must use the same
reference picture. Profile sharing omits custom model prompts, preferences,
learned icons and hidden image metadata. Check visible pictures and names
before sharing them.

8. ASK YOUR OWN MODEL TO SUGGEST A PATH — OPTIONAL

1) In Model planning, choose Draw path from image.
2) Select resource types in Routes. Catalog resources appear in the export
   picture and JSON even if your current route is empty.
3) Write your prompt, such as a short Gems and Od loop using bridges.
4) Click Export model pack (image + JSON), then extract that ZIP.
5) Give map.png, legend.png and task.json to your image-capable model.
   Copy the instructions from PROMPT.txt and request its JSON response.
6) Save the response as .json and click Import model response JSON.

The result is a new editable route. Review estimated positions, cliffs,
rivers and access. Known database resources retain their exact type and
position when the model chooses their resource IDs. Filtered catalog may
need Allow model to choose a subset if over 1000 stops are selected. Image
mode with an empty Current route can choose from the resource pool.
AetherRoute does not contact models or require an API key.

9. SETTINGS AND OPTIONAL CUSTOM TOOLS

Settings lets you disable the launcher, start with the main window visible,
or turn off keeping the main window above the game.

Developer mode reveals custom database/map imports, bounds and catalogs.
Learn icon and Import icons let you teach screenshot symbols locally.
Choose a stop's resource Type first, then Learn icon and select a tight
rectangle around the symbol. Import icons can reuse an older samples folder.
Once learned or imported, samples keep typing picture icons automatically
when Developer mode is off. Ctrl + click always uses your chosen Type.
See MAP-PACKS.txt for custom worlds. Normal use needs none of these steps.

10. IF SOMETHING LOOKS WRONG

- Map opens in a corner: the canvas now fits after layout. Fit map / reset
  area remains available to return to the complete world.
- No overlay: check the active zone, bind the game again, show the matching
  terrain, use Windowed/Borderless mode and wait for alignment.
- Minimap drift: use high map opacity and re-select its terrain boundary.
- Wrong picture type: choose Type and Apply to selected, or use the icon
  tools in Developer mode. Included database resources type automatically.
- No launcher: Settings may disable it. Use the taskbar to reopen an
  iconified main window. Quit fully closes the app.

Saved data stays in %LOCALAPPDATA%\Aion2RouteSync, preserving upgrades.
Export profile is the simplest backup. Do not delete this folder to upgrade.
