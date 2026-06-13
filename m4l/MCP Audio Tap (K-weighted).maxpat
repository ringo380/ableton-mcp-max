{
	"patcher" : 	{
		"fileversion" : 1,
		"appversion" : 		{
			"major" : 8,
			"minor" : 5,
			"revision" : 5,
			"architecture" : "x64",
			"modernui" : 1
		},
		"classnamespace" : "box",
		"rect" : [ 60.0, 60.0, 900.0, 700.0 ],
		"boxes" : [
			{
				"box" : 				{
					"id" : "obj-1",
					"maxclass" : "newobj",
					"text" : "plugin~",
					"numinlets" : 0,
					"numoutlets" : 2,
					"outlettype" : [ "signal", "signal" ],
					"patching_rect" : [ 30.0, 30.0, 60.0, 22.0 ]
				}

			}
,
			{
				"box" : 				{
					"id" : "obj-2",
					"maxclass" : "newobj",
					"text" : "plugout~",
					"numinlets" : 2,
					"numoutlets" : 0,
					"patching_rect" : [ 30.0, 620.0, 65.0, 22.0 ]
				}

			}
,
			{
				"box" : 				{
					"id" : "obj-18",
					"maxclass" : "newobj",
					"text" : "loadmess 1.53512485958697 -2.69169618940638 1.19839281085285 -1.69065929318241 0.73248077421585",
					"numinlets" : 1,
					"numoutlets" : 1,
					"outlettype" : [ "" ],
					"patching_rect" : [ 470.0, 30.0, 520.0, 22.0 ]
				}

			}
,
			{
				"box" : 				{
					"id" : "obj-19",
					"maxclass" : "newobj",
					"text" : "loadmess 1. -2. 1. -1.99004745483398 0.99007225036621",
					"numinlets" : 1,
					"numoutlets" : 1,
					"outlettype" : [ "" ],
					"patching_rect" : [ 470.0, 70.0, 330.0, 22.0 ]
				}

			}
,
			{
				"box" : 				{
					"id" : "obj-3",
					"maxclass" : "newobj",
					"text" : "biquad~",
					"numinlets" : 6,
					"numoutlets" : 1,
					"outlettype" : [ "signal" ],
					"patching_rect" : [ 180.0, 90.0, 120.0, 22.0 ]
				}

			}
,
			{
				"box" : 				{
					"id" : "obj-4",
					"maxclass" : "newobj",
					"text" : "biquad~",
					"numinlets" : 6,
					"numoutlets" : 1,
					"outlettype" : [ "signal" ],
					"patching_rect" : [ 180.0, 140.0, 120.0, 22.0 ]
				}

			}
,
			{
				"box" : 				{
					"id" : "obj-5",
					"maxclass" : "newobj",
					"text" : "*~",
					"numinlets" : 2,
					"numoutlets" : 1,
					"outlettype" : [ "signal" ],
					"patching_rect" : [ 180.0, 190.0, 40.0, 22.0 ]
				}

			}
,
			{
				"box" : 				{
					"id" : "obj-6",
					"maxclass" : "newobj",
					"text" : "average~ 4800",
					"numinlets" : 1,
					"numoutlets" : 1,
					"outlettype" : [ "signal" ],
					"patching_rect" : [ 180.0, 240.0, 100.0, 22.0 ]
				}

			}
,
			{
				"box" : 				{
					"id" : "obj-7",
					"maxclass" : "newobj",
					"text" : "snapshot~ 100",
					"numinlets" : 1,
					"numoutlets" : 1,
					"outlettype" : [ "float" ],
					"patching_rect" : [ 180.0, 290.0, 95.0, 22.0 ]
				}

			}
,
			{
				"box" : 				{
					"id" : "obj-8",
					"maxclass" : "newobj",
					"text" : "biquad~",
					"numinlets" : 6,
					"numoutlets" : 1,
					"outlettype" : [ "signal" ],
					"patching_rect" : [ 340.0, 90.0, 120.0, 22.0 ]
				}

			}
,
			{
				"box" : 				{
					"id" : "obj-9",
					"maxclass" : "newobj",
					"text" : "biquad~",
					"numinlets" : 6,
					"numoutlets" : 1,
					"outlettype" : [ "signal" ],
					"patching_rect" : [ 340.0, 140.0, 120.0, 22.0 ]
				}

			}
,
			{
				"box" : 				{
					"id" : "obj-10",
					"maxclass" : "newobj",
					"text" : "*~",
					"numinlets" : 2,
					"numoutlets" : 1,
					"outlettype" : [ "signal" ],
					"patching_rect" : [ 340.0, 190.0, 40.0, 22.0 ]
				}

			}
,
			{
				"box" : 				{
					"id" : "obj-11",
					"maxclass" : "newobj",
					"text" : "average~ 4800",
					"numinlets" : 1,
					"numoutlets" : 1,
					"outlettype" : [ "signal" ],
					"patching_rect" : [ 340.0, 240.0, 100.0, 22.0 ]
				}

			}
,
			{
				"box" : 				{
					"id" : "obj-12",
					"maxclass" : "newobj",
					"text" : "snapshot~ 100",
					"numinlets" : 1,
					"numoutlets" : 1,
					"outlettype" : [ "float" ],
					"patching_rect" : [ 340.0, 290.0, 95.0, 22.0 ]
				}

			}
,
			{
				"box" : 				{
					"id" : "obj-13",
					"maxclass" : "newobj",
					"text" : "peakamp~ 100",
					"numinlets" : 2,
					"numoutlets" : 1,
					"outlettype" : [ "float" ],
					"patching_rect" : [ 520.0, 190.0, 95.0, 22.0 ]
				}

			}
,
			{
				"box" : 				{
					"id" : "obj-14",
					"maxclass" : "newobj",
					"text" : "peakamp~ 100",
					"numinlets" : 2,
					"numoutlets" : 1,
					"outlettype" : [ "float" ],
					"patching_rect" : [ 630.0, 190.0, 95.0, 22.0 ]
				}

			}
,
			{
				"box" : 				{
					"id" : "obj-15",
					"maxclass" : "newobj",
					"text" : "max 0.",
					"numinlets" : 2,
					"numoutlets" : 1,
					"outlettype" : [ "" ],
					"patching_rect" : [ 520.0, 290.0, 60.0, 22.0 ]
				}

			}
,
			{
				"box" : 				{
					"id" : "obj-16",
					"maxclass" : "newobj",
					"text" : "pak block 0. 0. 0.",
					"numinlets" : 4,
					"numoutlets" : 1,
					"outlettype" : [ "" ],
					"patching_rect" : [ 180.0, 360.0, 140.0, 22.0 ]
				}

			}
,
			{
				"box" : 				{
					"id" : "obj-17",
					"maxclass" : "newobj",
					"text" : "node.script tap-server.js @autostart 1",
					"numinlets" : 1,
					"numoutlets" : 2,
					"outlettype" : [ "", "" ],
					"patching_rect" : [ 180.0, 420.0, 230.0, 22.0 ]
				}

			}
,
			{
				"box" : 				{
					"id" : "obj-20",
					"maxclass" : "comment",
					"text" : "MCP Audio Tap - BS.1770 K-weighted loudness + sample-peak",
					"numinlets" : 1,
					"numoutlets" : 0,
					"patching_rect" : [ 30.0, 480.0, 380.0, 20.0 ]
				}

			}
 ],
		"lines" : [
			{ "patchline" : { "source" : [ "obj-1", 0 ], "destination" : [ "obj-2", 0 ] } }
,
			{ "patchline" : { "source" : [ "obj-1", 1 ], "destination" : [ "obj-2", 1 ] } }
,
			{ "patchline" : { "source" : [ "obj-1", 0 ], "destination" : [ "obj-3", 0 ] } }
,
			{ "patchline" : { "source" : [ "obj-1", 1 ], "destination" : [ "obj-8", 0 ] } }
,
			{ "patchline" : { "source" : [ "obj-1", 0 ], "destination" : [ "obj-13", 0 ] } }
,
			{ "patchline" : { "source" : [ "obj-1", 1 ], "destination" : [ "obj-14", 0 ] } }
,
			{ "patchline" : { "source" : [ "obj-3", 0 ], "destination" : [ "obj-4", 0 ] } }
,
			{ "patchline" : { "source" : [ "obj-4", 0 ], "destination" : [ "obj-5", 0 ] } }
,
			{ "patchline" : { "source" : [ "obj-4", 0 ], "destination" : [ "obj-5", 1 ] } }
,
			{ "patchline" : { "source" : [ "obj-5", 0 ], "destination" : [ "obj-6", 0 ] } }
,
			{ "patchline" : { "source" : [ "obj-6", 0 ], "destination" : [ "obj-7", 0 ] } }
,
			{ "patchline" : { "source" : [ "obj-7", 0 ], "destination" : [ "obj-16", 1 ] } }
,
			{ "patchline" : { "source" : [ "obj-8", 0 ], "destination" : [ "obj-9", 0 ] } }
,
			{ "patchline" : { "source" : [ "obj-9", 0 ], "destination" : [ "obj-10", 0 ] } }
,
			{ "patchline" : { "source" : [ "obj-9", 0 ], "destination" : [ "obj-10", 1 ] } }
,
			{ "patchline" : { "source" : [ "obj-10", 0 ], "destination" : [ "obj-11", 0 ] } }
,
			{ "patchline" : { "source" : [ "obj-11", 0 ], "destination" : [ "obj-12", 0 ] } }
,
			{ "patchline" : { "source" : [ "obj-12", 0 ], "destination" : [ "obj-16", 2 ] } }
,
			{ "patchline" : { "source" : [ "obj-13", 0 ], "destination" : [ "obj-15", 0 ] } }
,
			{ "patchline" : { "source" : [ "obj-14", 0 ], "destination" : [ "obj-15", 1 ] } }
,
			{ "patchline" : { "source" : [ "obj-15", 0 ], "destination" : [ "obj-16", 3 ] } }
,
			{ "patchline" : { "source" : [ "obj-16", 0 ], "destination" : [ "obj-17", 0 ] } }
,
			{ "patchline" : { "source" : [ "obj-18", 0 ], "destination" : [ "obj-3", 0 ] } }
,
			{ "patchline" : { "source" : [ "obj-18", 0 ], "destination" : [ "obj-8", 0 ] } }
,
			{ "patchline" : { "source" : [ "obj-19", 0 ], "destination" : [ "obj-4", 0 ] } }
,
			{ "patchline" : { "source" : [ "obj-19", 0 ], "destination" : [ "obj-9", 0 ] } }
 ]
	}

}
