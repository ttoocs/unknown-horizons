# ###################################################
# Copyright (C) 2008 The OpenAnno Team
# team@openanno.org
# This file is part of OpenAnno.
#
# OpenAnno is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the
# Free Software Foundation, Inc.,
# 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
# ###################################################

import math
import shutil
import os
import os.path
import time

import fife

import game.main
from game.gui.selectiontool import SelectionTool
from game.world.building import building
from game.world.units.ship import Ship
from game.world.player import Player
from game.gui.ingamegui import IngameGui
from game.gui.ingamekeylistener import IngameKeyListener
from game.world.island import Island
from game.dbreader import DbReader
from game.timer import Timer
from game.scheduler import Scheduler
from game.manager import SPManager
from game.view import View
from game.world import World
from game.entities import Entities
from game.util import livingProperty, WorldObject

class Session(object):
	"""Session class represents the games main ingame view and controls cameras and map loading.

	This is the most important class if you are going to hack on OpenAnno, it provides most of
	the important ingame variables that you will be constantly accessing by game.main.session.x
	Here's a small list of commonly used attributes:
	* manager - game.manager instance. Used to execute commands that need to be tick,
				synchronized check the class for more information.
	* scheduler - game.scheduler instance. Used to execute timed events that do not effect
	              network game.
	* view - game.view instance. Used to control the ingame camera.
	* entities - game.entities instance. used to hold preconstructed dummy classes from the db
	             for later initialization.
	* ingame_gui - game.gui.ingame_gui instance. Used to controll the ingame gui.
	* cursor - game.gui.{navigation/cursor/selection/building}tool instance. Used to controll
			   mouse events, check the classes for more info.
	* selected_instances - Set that holds the currently selected instances (building, units).
	* world - game.world instance of the currently running game. Stores islands, players,
	          for later access.

	TUTORIAL:
	For further digging you should now be checking out the load() function.
	"""
	timer = livingProperty()
	manager = livingProperty()
	scheduler = livingProperty()
	view = livingProperty()
	entities = livingProperty()
	ingame_gui = livingProperty()
	keylistener = livingProperty()
	cursor = livingProperty()
	world = livingProperty()

	def __init__(self):
		super(Session, self).__init__()

	def init_session(self):

		WorldObject.reset()

		#game
		self.timer = Timer()
		self.manager = SPManager()
		self.scheduler = Scheduler(self.timer)
		self.view = View((15, 15))
		self.entities = Entities()

		#GUI
		self.ingame_gui = IngameGui()
		self.keylistener = IngameKeyListener()
		self.cursor = SelectionTool()

		self.selected_instances = set()
		self.selection_groups = [set()] * 10 # List of sets that holds the player assigned unit groups.

		#autosave
		#if game.main.settings.savegame.autosaveinterval != 0:
		#game.main.ext_scheduler.add_new_object(self.autosave, self.autosave, game.main.settings.savegame.autosaveinterval * 60, -1)

	def __del__(self):
		self.scheduler.rem_all_classinst_calls(self)

		self.cursor = None
		self.keylistener = None
		self.ingame_gui = None
		self.entities = None
		self.view = None
		self.scheduler = None
		self.manager = None
		self.timer = None
		self.world = None

		self.selected_instances = None
		self.selection_groups = None
		super(Session, self).__del__()

	def autosave(self):
		"""Called automatically in an interval"""
		self.save(game.main.savegamemanager.create_autosave_filename())
		game.main.savegamemanager.delete_dispensable_savegames(autosaves = True)

	def quicksave(self):
		"""Called when user presses a hotkey"""
		self.save(game.main.savegamemanager.create_quicksave_filename())
		game.main.savegamemanager.delete_dispensable_savegames(quicksaves = True)

	def quickload(self):
		"""Loads last quicksave"""
		files = game.main.savegamemanager.get_quicksaves(include_displaynames = False)[0]
		if len(files) == 0:
			game.main.showPopup("No quicksaves found", "You need to quicksave before you can quickload.")
			return
		files.sort()
		game.main.gui.load_game(files[-1])

	def save(self, savegame):
		"""
		@param savegame: the file, where the game will be saved
		"""
		if os.path.exists(savegame):
			os.unlink(savegame)
		shutil.copyfile('content/savegame_template.sqlite', savegame)

		db = DbReader(savegame)
		try:
			print 'STARTING SAVING'
			db("BEGIN")
			self.world.save(db)
			#self.manager.save(db)
			self.view.save(db)
			self.ingame_gui.save(db)

			for instance in self.selected_instances:
				db("INSERT INTO selected(`group`, id) VALUES(NULL, ?)", instance.getId())
			for group in xrange(len(self.selection_groups)):
				for instance in self.selection_groups[group]:
					db("INSERT INTO selected(`group`, id) VALUES(?, ?)", group, instance.getId())

			print 'writing metadata'
			game.main.savegamemanager.write_metadata(db)
		except Exception, e:
			print "Save exception", e
		finally:
			db("COMMIT")
			print 'FINISHED SAVING'

	def record(self, savegame):
		self.save(savegame)
		game.main.db("ATTACH ? AS demo", savegame)
		self.manager.recording = True

	def stop_record(self):
		assert(self.manager.recording)
		self.manager.recording = False
		game.main.db("DETACH demo")

	def load(self, savegame, playername = "", playercolor = None):
		"""Loads a map.
		@param savegame: path to the savegame database.
		@param playername: string with the playername
		@param playercolor: game.util.color instance with the player's color
		"""
		db = DbReader(savegame) # Initialize new dbreader
		self.world = World() # Load game.world module (check game/world/__init__.py)
		self.world._init(db)
		if playername != "":
			self.world.setupPlayer(playername, playercolor) # setup new player
		self.view.load(db) # load view
		self.manager.load(db) # load the manager (there might me old scheduled ticks.
		self.ingame_gui.load(db) # load the old gui positions and stuff
		#setup view
		#self.view.center(((self.world.max_x - self.world.min_x) / 2.0), ((self.world.max_y - self.world.min_y) / 2.0))

		for instance_id in db("SELECT id FROM selected WHERE `group` IS NULL"): # Set old selected instance
			obj = WorldObject.getObjectById(instance_id[0])
			self.selected_instances.add(obj)
			obj.select()
		for group in xrange(len(self.selection_groups)): # load user defined unit groups
			for instance_id in db("SELECT id FROM selected WHERE `group` = ?", group):
				self.selection_groups[group].add(WorldObject.getObjectById(instance_id[0]))

		self.cursor.apply_select() # Set cursor correctly, menus might need to be opened.

		"""
		TUTORIAL:
		From here on you should digg into the classes that are loaded above, especially the world class.
		(game/world/__init__.py). It's where the magic happens and all buildings and units are loaded.
		"""

	def generateMap(self):
		"""Generates a map."""

		#load map
		game.main.db("attach ':memory:' as map")
		#...
		self.world = World()
		self.world._init(game.main.db)

		#setup view
		self.view.center(((self.world.max_x - self.world.min_x) / 2.0), ((self.world.max_y - self.world.min_y) / 2.0))

	def speed_set(self, ticks):
		old = self.timer.ticks_per_second
		self.timer.ticks_per_second = ticks
		self.view.map.setTimeMultiplier(float(ticks) / float(game.main.settings.ticks.default))
		if old == 0 and self.timer.tick_next_time is None: #back from paused state
			self.timer.tick_next_time = time.time() + (self.paused_time_missing / ticks)
		elif ticks == 0 or self.timer.tick_next_time is None: #go into paused state or very early speed change (before any tick)
			self.paused_time_missing = ((self.timer.tick_next_time - time.time()) * old) if self.timer.tick_next_time is not None else None
			self.timer.tick_next_time = None
		else:
			self.timer.tick_next_time = self.timer.tick_next_time + ((self.timer.tick_next_time - time.time()) * old / ticks)

	def speed_up(self):
		if self.timer.ticks_per_second in game.main.settings.ticks.steps:
			i = game.main.settings.ticks.steps.index(self.timer.ticks_per_second)
			if i + 1 < len(game.main.settings.ticks.steps):
				self.speed_set(game.main.settings.ticks.steps[i + 1])
		else:
			self.speed_set(game.main.settings.ticks.steps[0])

	def speed_down(self):
		if self.timer.ticks_per_second in game.main.settings.ticks.steps:
			i = game.main.settings.ticks.steps.index(self.timer.ticks_per_second)
			if i > 0:
				self.speed_set(game.main.settings.ticks.steps[i - 1])
		else:
			self.speed_set(game.main.settings.ticks.steps[0])

	def speed_pause(self):
		if self.timer.ticks_per_second != 0:
			self.paused_ticks_per_second = self.timer.ticks_per_second
			self.speed_set(0)

	def speed_unpause(self):
		if self.timer.ticks_per_second == 0:
			self.speed_set(self.paused_ticks_per_second)


	def speed_toggle_pause(self):
		if self.timer.ticks_per_second == 0:
			self.speed_unpause()
		else:
			self.speed_pause()
