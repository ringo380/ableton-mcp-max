{
 "patcher": {
  "fileversion": 1,
  "appversion": {
   "major": 8,
   "minor": 5,
   "revision": 8,
   "architecture": "x64",
   "modernui": 1
  },
  "classnamespace": "box",
  "rect": [
   34.0,
   93.0,
   1826.0,
   1306.0
  ],
  "openrect": [
   0.0,
   0.0,
   0.0,
   169.0
  ],
  "bglocked": 0,
  "openinpresentation": 0,
  "default_fontsize": 10.0,
  "default_fontface": 0,
  "default_fontname": "Arial Bold",
  "gridonopen": 1,
  "gridsize": [
   8.0,
   8.0
  ],
  "gridsnaponopen": 1,
  "objectsnaponopen": 1,
  "statusbarvisible": 2,
  "toolbarvisible": 1,
  "lefttoolbarpinned": 0,
  "toptoolbarpinned": 0,
  "righttoolbarpinned": 0,
  "bottomtoolbarpinned": 0,
  "toolbars_unpinned_last_save": 0,
  "tallnewobj": 0,
  "boxanimatetime": 500,
  "enablehscroll": 1,
  "enablevscroll": 1,
  "devicewidth": 0.0,
  "description": "",
  "digest": "",
  "tags": "",
  "style": "",
  "subpatcher_template": "",
  "assistshowspatchername": 0,
  "boxes": [
   {
    "box": {
     "id": "obj-11",
     "maxclass": "live.comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      32.0,
      115.0,
      19.0,
      18.0
     ],
     "text": "L",
     "textjustification": 0
    }
   },
   {
    "box": {
     "id": "obj-10",
     "maxclass": "live.comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      32.0,
      34.0,
      19.0,
      18.0
     ],
     "text": "L",
     "textjustification": 0
    }
   },
   {
    "box": {
     "id": "obj-8",
     "maxclass": "live.comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      105.0,
      35.0,
      19.0,
      18.0
     ],
     "text": "R",
     "textjustification": 0
    }
   },
   {
    "box": {
     "id": "obj-7",
     "maxclass": "live.comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      104.0,
      115.0,
      19.0,
      18.0
     ],
     "text": "R",
     "textjustification": 0
    }
   },
   {
    "box": {
     "id": "obj-5",
     "maxclass": "live.comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      43.0,
      136.0,
      63.0,
      18.0
     ],
     "text": "Audio to Live",
     "textjustification": 0
    }
   },
   {
    "box": {
     "id": "obj-3",
     "maxclass": "live.comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      38.0,
      16.0,
      74.0,
      18.0
     ],
     "text": "Audio from Live",
     "textjustification": 0
    }
   },
   {
    "box": {
     "fontname": "Ableton Sans Medium Regular",
     "fontsize": 11.0,
     "hidden": 1,
     "id": "obj-9",
     "maxclass": "comment",
     "numinlets": 1,
     "numoutlets": 0,
     "patching_rect": [
      0.0,
      170.0,
      134.0,
      20.0
     ],
     "text": "Device vertical limit"
    }
   },
   {
    "box": {
     "fontname": "Arial Bold",
     "fontsize": 10.0,
     "id": "obj-2",
     "maxclass": "newobj",
     "numinlets": 2,
     "numoutlets": 2,
     "outlettype": [
      "signal",
      "signal"
     ],
     "patching_rect": [
      48.0,
      114.0,
      53.0,
      20.0
     ],
     "text": "plugout~"
    }
   },
   {
    "box": {
     "fontname": "Arial Bold",
     "fontsize": 10.0,
     "id": "obj-1",
     "maxclass": "newobj",
     "numinlets": 2,
     "numoutlets": 2,
     "outlettype": [
      "signal",
      "signal"
     ],
     "patching_rect": [
      48.0,
      34.0,
      53.0,
      20.0
     ],
     "text": "plugin~"
    }
   },
   {
    "box": {
     "id": "kw-1",
     "maxclass": "newobj",
     "numinlets": 6,
     "numoutlets": 1,
     "patching_rect": [
      180,
      90,
      120,
      22
     ],
     "text": "biquad~",
     "outlettype": [
      "signal"
     ]
    }
   },
   {
    "box": {
     "id": "kw-2",
     "maxclass": "newobj",
     "numinlets": 6,
     "numoutlets": 1,
     "patching_rect": [
      180,
      140,
      120,
      22
     ],
     "text": "biquad~",
     "outlettype": [
      "signal"
     ]
    }
   },
   {
    "box": {
     "id": "kw-3",
     "maxclass": "newobj",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      180,
      190,
      40,
      22
     ],
     "text": "*~",
     "outlettype": [
      "signal"
     ]
    }
   },
   {
    "box": {
     "id": "kw-4",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 1,
     "patching_rect": [
      180,
      240,
      100,
      22
     ],
     "text": "average~ 4800",
     "outlettype": [
      "signal"
     ]
    }
   },
   {
    "box": {
     "id": "kw-5",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 1,
     "patching_rect": [
      180,
      290,
      95,
      22
     ],
     "text": "snapshot~ 100",
     "outlettype": [
      "float"
     ]
    }
   },
   {
    "box": {
     "id": "kw-6",
     "maxclass": "newobj",
     "numinlets": 6,
     "numoutlets": 1,
     "patching_rect": [
      340,
      90,
      120,
      22
     ],
     "text": "biquad~",
     "outlettype": [
      "signal"
     ]
    }
   },
   {
    "box": {
     "id": "kw-7",
     "maxclass": "newobj",
     "numinlets": 6,
     "numoutlets": 1,
     "patching_rect": [
      340,
      140,
      120,
      22
     ],
     "text": "biquad~",
     "outlettype": [
      "signal"
     ]
    }
   },
   {
    "box": {
     "id": "kw-8",
     "maxclass": "newobj",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      340,
      190,
      40,
      22
     ],
     "text": "*~",
     "outlettype": [
      "signal"
     ]
    }
   },
   {
    "box": {
     "id": "kw-9",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 1,
     "patching_rect": [
      340,
      240,
      100,
      22
     ],
     "text": "average~ 4800",
     "outlettype": [
      "signal"
     ]
    }
   },
   {
    "box": {
     "id": "kw-10",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 1,
     "patching_rect": [
      340,
      290,
      95,
      22
     ],
     "text": "snapshot~ 100",
     "outlettype": [
      "float"
     ]
    }
   },
   {
    "box": {
     "id": "kw-11",
     "maxclass": "newobj",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      520,
      190,
      95,
      22
     ],
     "text": "peakamp~ 100",
     "outlettype": [
      "float"
     ]
    }
   },
   {
    "box": {
     "id": "kw-12",
     "maxclass": "newobj",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      630,
      190,
      95,
      22
     ],
     "text": "peakamp~ 100",
     "outlettype": [
      "float"
     ]
    }
   },
   {
    "box": {
     "id": "kw-13",
     "maxclass": "newobj",
     "numinlets": 2,
     "numoutlets": 1,
     "patching_rect": [
      520,
      290,
      120,
      22
     ],
     "text": "expr max($f1,$f2)",
     "outlettype": [
      ""
     ]
    }
   },
   {
    "box": {
     "id": "kw-14",
     "maxclass": "newobj",
     "numinlets": 4,
     "numoutlets": 1,
     "patching_rect": [
      180,
      360,
      140,
      22
     ],
     "text": "pak block 0. 0. 0.",
     "outlettype": [
      ""
     ]
    }
   },
   {
    "box": {
     "id": "kw-15",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 2,
     "patching_rect": [
      180,
      420,
      230,
      22
     ],
     "text": "node.script registry-client.js @autostart 1",
     "outlettype": [
      "",
      ""
     ]
    }
   },
   {
    "box": {
     "id": "kw-16",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 1,
     "patching_rect": [
      470,
      30,
      520,
      22
     ],
     "text": "loadmess 1.53512485958697 -2.69169618940638 1.19839281085285 -1.69065929318241 0.73248077421585",
     "outlettype": [
      ""
     ]
    }
   },
   {
    "box": {
     "id": "kw-17",
     "maxclass": "newobj",
     "numinlets": 1,
     "numoutlets": 1,
     "patching_rect": [
      470,
      70,
      330,
      22
     ],
     "text": "loadmess 1. -2. 1. -1.99004745483398 0.99007225036621",
     "outlettype": [
      ""
     ]
    }
   },
   {
    "box": {
     "id": "sid-1",
     "maxclass": "newobj",
     "text": "live.thisdevice",
     "patching_rect": [
      680,
      15,
      110,
      22
     ],
     "numinlets": 1,
     "numoutlets": 3
    }
   },
   {
    "box": {
     "id": "sid-2",
     "maxclass": "newobj",
     "text": "t 1",
     "patching_rect": [
      680,
      45,
      30,
      22
     ],
     "numinlets": 1,
     "numoutlets": 1
    }
   },
   {
    "box": {
     "id": "sid-3",
     "maxclass": "newobj",
     "text": "metro 1500",
     "patching_rect": [
      680,
      75,
      80,
      22
     ],
     "numinlets": 2,
     "numoutlets": 1
    }
   },
   {
    "box": {
     "id": "sid-4",
     "maxclass": "newobj",
     "text": "live.path this_device",
     "patching_rect": [
      440,
      75,
      150,
      22
     ],
     "numinlets": 1,
     "numoutlets": 3
    }
   },
   {
    "box": {
     "id": "sid-5",
     "maxclass": "newobj",
     "text": "live.object",
     "patching_rect": [
      440,
      135,
      90,
      22
     ],
     "numinlets": 2,
     "numoutlets": 2
    }
   },
   {
    "box": {
     "id": "sid-6",
     "maxclass": "message",
     "text": "get canonical_parent",
     "patching_rect": [
      620,
      105,
      150,
      22
     ],
     "numinlets": 2,
     "numoutlets": 1
    }
   },
   {
    "box": {
     "id": "sid-7",
     "maxclass": "newobj",
     "text": "route canonical_parent",
     "patching_rect": [
      440,
      165,
      160,
      22
     ],
     "numinlets": 1,
     "numoutlets": 2
    }
   },
   {
    "box": {
     "id": "sid-8",
     "maxclass": "newobj",
     "text": "prepend trk",
     "patching_rect": [
      440,
      195,
      90,
      22
     ],
     "numinlets": 1,
     "numoutlets": 1
    }
   },
   {
    "box": {
     "id": "sid-9",
     "maxclass": "newobj",
     "text": "live.path live_set",
     "patching_rect": [
      120,
      75,
      130,
      22
     ],
     "numinlets": 1,
     "numoutlets": 3
    }
   },
   {
    "box": {
     "id": "sid-10",
     "maxclass": "newobj",
     "text": "live.object",
     "patching_rect": [
      120,
      135,
      90,
      22
     ],
     "numinlets": 2,
     "numoutlets": 2
    }
   },
   {
    "box": {
     "id": "sid-11",
     "maxclass": "message",
     "text": "get tracks",
     "patching_rect": [
      120,
      105,
      90,
      22
     ],
     "numinlets": 2,
     "numoutlets": 1
    }
   },
   {
    "box": {
     "id": "sid-12",
     "maxclass": "message",
     "text": "get return_tracks",
     "patching_rect": [
      220,
      105,
      130,
      22
     ],
     "numinlets": 2,
     "numoutlets": 1
    }
   },
   {
    "box": {
     "id": "sid-13",
     "maxclass": "message",
     "text": "get master_track",
     "patching_rect": [
      360,
      105,
      130,
      22
     ],
     "numinlets": 2,
     "numoutlets": 1
    }
   },
   {
    "box": {
     "id": "sid-14",
     "maxclass": "newobj",
     "text": "prepend song",
     "patching_rect": [
      120,
      165,
      100,
      22
     ],
     "numinlets": 1,
     "numoutlets": 1
    }
   }
  ],
  "lines": [
   {
    "patchline": {
     "destination": [
      "obj-2",
      1
     ],
     "source": [
      "obj-1",
      1
     ]
    }
   },
   {
    "patchline": {
     "destination": [
      "obj-2",
      0
     ],
     "source": [
      "obj-1",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-1",
      0
     ],
     "destination": [
      "kw-1",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-1",
      1
     ],
     "destination": [
      "kw-6",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-1",
      0
     ],
     "destination": [
      "kw-11",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "obj-1",
      1
     ],
     "destination": [
      "kw-12",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "kw-1",
      0
     ],
     "destination": [
      "kw-2",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "kw-2",
      0
     ],
     "destination": [
      "kw-3",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "kw-2",
      0
     ],
     "destination": [
      "kw-3",
      1
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "kw-3",
      0
     ],
     "destination": [
      "kw-4",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "kw-4",
      0
     ],
     "destination": [
      "kw-5",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "kw-5",
      0
     ],
     "destination": [
      "kw-14",
      1
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "kw-6",
      0
     ],
     "destination": [
      "kw-7",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "kw-7",
      0
     ],
     "destination": [
      "kw-8",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "kw-7",
      0
     ],
     "destination": [
      "kw-8",
      1
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "kw-8",
      0
     ],
     "destination": [
      "kw-9",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "kw-9",
      0
     ],
     "destination": [
      "kw-10",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "kw-10",
      0
     ],
     "destination": [
      "kw-14",
      2
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "kw-11",
      0
     ],
     "destination": [
      "kw-13",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "kw-12",
      0
     ],
     "destination": [
      "kw-13",
      1
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "kw-13",
      0
     ],
     "destination": [
      "kw-14",
      3
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "kw-14",
      0
     ],
     "destination": [
      "kw-15",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "kw-16",
      0
     ],
     "destination": [
      "kw-1",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "kw-16",
      0
     ],
     "destination": [
      "kw-6",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "kw-17",
      0
     ],
     "destination": [
      "kw-2",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "kw-17",
      0
     ],
     "destination": [
      "kw-7",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "sid-1",
      0
     ],
     "destination": [
      "sid-2",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "sid-2",
      0
     ],
     "destination": [
      "sid-3",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "sid-4",
      0
     ],
     "destination": [
      "sid-5",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "sid-3",
      0
     ],
     "destination": [
      "sid-6",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "sid-6",
      0
     ],
     "destination": [
      "sid-5",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "sid-5",
      0
     ],
     "destination": [
      "sid-7",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "sid-7",
      0
     ],
     "destination": [
      "sid-8",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "sid-8",
      0
     ],
     "destination": [
      "kw-15",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "sid-9",
      0
     ],
     "destination": [
      "sid-10",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "sid-3",
      0
     ],
     "destination": [
      "sid-11",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "sid-3",
      0
     ],
     "destination": [
      "sid-12",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "sid-3",
      0
     ],
     "destination": [
      "sid-13",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "sid-11",
      0
     ],
     "destination": [
      "sid-10",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "sid-12",
      0
     ],
     "destination": [
      "sid-10",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "sid-13",
      0
     ],
     "destination": [
      "sid-10",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "sid-10",
      0
     ],
     "destination": [
      "sid-14",
      0
     ]
    }
   },
   {
    "patchline": {
     "source": [
      "sid-14",
      0
     ],
     "destination": [
      "kw-15",
      0
     ]
    }
   }
  ],
  "dependency_cache": [
   {
    "name": "tap-server.js",
    "bootpath": "~/git/ableton-mcp-max/m4l",
    "type": "TEXT",
    "implicit": 1
   }
  ],
  "latency": 0,
  "is_mpe": 0,
  "minimum_live_version": "",
  "minimum_max_version": "",
  "platform_compatibility": 0,
  "project": {
   "version": 1,
   "creationdate": 3590052493,
   "modificationdate": 3590052493,
   "viewrect": [
    0.0,
    0.0,
    300.0,
    500.0
   ],
   "autoorganize": 1,
   "hideprojectwindow": 1,
   "showdependencies": 1,
   "autolocalize": 0,
   "contents": {
    "patchers": {},
    "code": {}
   },
   "layout": {},
   "searchpath": {},
   "detailsvisible": 0,
   "amxdtype": 1633771873,
   "readonly": 0,
   "devpathtype": 0,
   "devpath": ".",
   "sortmode": 0,
   "viewmode": 0,
   "includepackages": 0
  },
  "autosave": 0,
  "saved_attribute_attributes": {
   "default_plcolor": {
    "expression": ""
   }
  }
 }
}