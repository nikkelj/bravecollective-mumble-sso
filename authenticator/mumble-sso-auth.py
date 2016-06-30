#!/usr/bin/env python

import os, sys, time, re
import MySQLdb, ConfigParser
import logging, logging.handlers
import sqlite3
import Ice
Ice.loadSlice('',['-I' + Ice.getSliceDir(),'/usr/share/slice/Murmur.ice'])
# ^ Sometimes the import of ice files fail. Try enforce an include path like that:
# Ice.loadSlice("--all -I/usr/share/Ice-3.5.1/slice/ /usr/share/slice/Murmur.ice")
import Murmur

# -------------------------------------------------------------------------------
logger = logging.getLogger("auth")
logger.setLevel(logging.DEBUG)
handler = logging.handlers.RotatingFileHandler("/var/log/mumble-auth-py.log",maxBytes=(1048576*5),backupCount=7)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(formatter)
logger.addHandler(consoleHandler)

cfg = '/data/sso/mumble/authenticator/mumble-sso-auth.ini'
logger.info(('Reading config file: {0}').format(cfg))
config = ConfigParser.RawConfigParser()
config.read(cfg)

server_id = config.getint('murmur', 'server_id')

sql_name = config.get('mysql', 'sql_name')
sql_user = config.get('mysql', 'sql_user')
sql_pass = config.get('mysql', 'sql_pass')
sql_host = config.get('mysql', 'sql_host')

sqlitedb = config.get('sqlite','dbfile')

logger.info("MySQL DB Info: " + str(sql_name) + " : " + str(sql_user) + " : " + str(sql_pass) + " : " + str(sql_host))
logger.info("SQlite DB Info: " + str(sqlitedb))

display_name = config.get('misc', 'display_name')
restrict_access_by_ticker = config.get('misc', 'restrict_access_by_ticker')
logger.info("Settings: " + str(display_name) + " : " + str(restrict_access_by_ticker))

# -------------------------------------------------------------------------------

try:
    db = MySQLdb.connect(sql_host, sql_user, sql_pass, sql_name)
    db.close()
    logging.info("Successful mysql db connect.")
    sqdb = sqlite3.connect(sqlitedb)
    sqdb.close()
    logging.info("Successful mumble sqlite db connect.")
except Exception, e:
    logging.error("Database intitialization failed: {0}".format(e))
    sys.exit(0)

# -------------------------------------------------------------------------------

class ServerAuthenticatorI(Murmur.ServerUpdatingAuthenticator):
	global server
	global logger
	def __init__(self, server, adapter):
		self.server = server
		self.logger = logger
	def authenticate(self, name, pw, certificates, certhash, cerstrong, out_newname):
	    try:
		db = MySQLdb.connect(sql_host, sql_user, sql_pass, sql_name)
		sqdb = sqlite3.connect(sqlitedb)
# ---- Verify Params

		if(not name or len(name) == 0):
			return (-1, None, None)

		self.logger.info(("Info: Trying '{0}'").format(name))
		#self.logger.info("Do we get here?")
		if(not pw or len(pw) == 0):
			self.logger.info(("Fail: {0} did not send a passsword").format(name))
			return (-1, None, None)
		#self.logger.info("Do we get here?")
# ---- Retrieve User

		ts_min = int(time.time()) - (60 * 60 * 48)
		c = db.cursor(MySQLdb.cursors.DictCursor)
		c.execute("SELECT * FROM user WHERE mumble_username = %s AND updated_at > %s", (name, ts_min))
		row = c.fetchone()
		c.close()
		#self.logger.info("Do we get here?2")
		if not row:
		    self.logger.info(("Fail: {0} not found in database").format(name))
		    return (-1, None, None)

		character_id = row['character_id']
		character_name = row['character_name']
		corporation_id = row['corporation_id']
		corporation_name = row['corporation_name']
		alliance_id = row['alliance_id']
		alliance_name = row['alliance_name']
		mumble_password = row['mumble_password']
		group_string = row['groups']

		logger.info(str(character_id) + " : " + str(character_name) + " : " + str(corporation_id) + " : " + str(alliance_id) + " : " + str(alliance_name) + " : " + str(mumble_password) + " : " + str(group_string))

		groups = []
		groups.append('corporation-' + str(corporation_id))
		groups.append('alliance-' + str(alliance_id))
		if group_string:
		    for g in group_string.split(','):
			groups.append(g.strip())

		logger.info("Groups are set: " + str(groups))
# ---- Verify Password
		logger.info(str(pw) + " : " + str(mumble_password))
		if mumble_password != pw:
		    self.logger.info("What formatting...")
		    self.logger.info(("Fail: {0} password does not match for {1}").format(name, character_id))
		    return (-1, None, None)
# ---- Check Bans
		logger.info("Checking bans...")
		c = db.cursor(MySQLdb.cursors.DictCursor)
		query = "SELECT * FROM ban WHERE filter = \'alliance-" + str(alliance_id)+ "\'"
		logger.info(query)
		c.execute(query)
		logger.info("Query complete.")
		#c.execute("SELECT * FROM ban WHERE filter = %s", ('alliance-' + str(alliance_id)))
		row = c.fetchone()
		c.close()
		logger.info("Ban query complete.")

		if row:
		    self.logger.info(("Fail: {0} alliance banned from server: {1} / {2}").format(name, row['reason_public'], row['reason_internal']))
		    return (-1, None, None)
		logger.info("Not alliance banned...")
		c = db.cursor(MySQLdb.cursors.DictCursor)
		query = "SELECT * FROM ban WHERE filter = \'corporation-"+str(corporation_id)+"\'"
		c.execute(query)
		#c.execute("SELECT * FROM ban WHERE filter = %s", ('corporation-' + str(corporation_id)))
		row = c.fetchone()
		c.close()

		if row:
		    self.logger.info(("Fail: {0} corporation banned from server: {1} / {2}").format(name, row['reason_public'], row['reason_internal']))
		    return (-1, None, None)
		logger.info("Not corp banned...")
		c = db.cursor(MySQLdb.cursors.DictCursor)
		query = "SELECT * FROM ban WHERE filter = \'character-"+str(character_id)+"\'"
		c.execute(query)
		#c.execute("SELECT * FROM ban WHERE filter = %s", ('character-' + str(character_id)))
		row = c.fetchone()
		c.close()

		if row:
		    self.logger.info(("Fail: {0} character banned from server: {1} / {2}").format(name, row['reason_public'], row['reason_internal']))
		    return (-1, None, None)
		logger.info("Not character banned...")
# ---- Retrieve tickers
		logger.info("Checking allowed tickers...")
		c = db.cursor(MySQLdb.cursors.DictCursor)
		query = "SELECT * FROM ticker WHERE filter = \'alliance-" + str(alliance_id)+ "\'"
		c.execute(query)
		#c.execute("SELECT * FROM ticker WHERE filter = %s", ('alliance-' + str(alliance_id)))
		rowa = c.fetchone()
		c.close()

		c = db.cursor(MySQLdb.cursors.DictCursor)
		query = "SELECT * FROM ticker WHERE filter = \'corporation-"+str(corporation_id)+"\'"
		c.execute(query)
		#c.execute("SELECT * FROM ticker WHERE filter = %s", ('corporation-' + str(corporation_id)))
		rowc = c.fetchone()
		c.close()

		ticker_alliance = '-----' if not rowa else rowa['text'];
		ticker_corporation = '-----' if not rowc else rowc['text'];

		if restrict_access_by_ticker == '1' and not (rowa or rowc):
		    self.logger.info(("Fail: {0} access requires one known ticker: {1} {2} {3} / {4} {5} {6}").format(name, corporation_id, ticker_corporation, corporation_name, alliance_id, ticker_alliance, alliance_name))
		    return (-1, None, None)
		if restrict_access_by_ticker == '2' and not (rowa and rowc):
		    self.logger.info(("Fail: {0} access requires two known ticker: {1} {2} {3} / {4} {5} {6}").format(name, corporation_id, ticker_corporation, corporation_name, alliance_id, ticker_alliance, alliance_name))
		    return (-1, None, None)

# ---- Generate Displayname

		nick = display_name
		nick = nick.replace('%A', ticker_alliance)
		nick = nick.replace('%C', ticker_corporation)
		nick = nick.replace('%N', character_name)
		logger.info("Nickname: " + str(nick))
# ---- Done


# --- Add Group Privs
		logger.info("Adding Mumble Group Privs...")
		try:
			#Alliance
			c = sqdb.cursor()
			query = "insert into group_members values ("
			query += "(select group_id from groups where name=\'alliance-"+str(alliance_id)+"\' and channel_id=0),"
			query += "1,"+str(character_id)+",1);"
			c.execute(query)
			sqdb.commit()
			
			#Admins
			c = db.cursor(MySQLdb.cursors.DictCursor)
			query = "select character_id from admin where character_id="+str(character_id)+";"
			c.execute(query)
			rowc = c.fetchone()
			c.close()
			if rowc:
				logger.info(character_name + " is flagged as an admin - adding to admin group.")
				c = sqdb.cursor()
				query = "insert into group_members values ("
				query += "(select group_id from groups where name=\'admin\' and channel_id=0),"
				query += "1,"+str(character_id)+",1);"
				c.execute(query)
				sqdb.commit()
			#FCs
			c = db.cursor(MySQLdb.cursors.DictCursor)
                        query = "select character_id from fc where character_id="+str(character_id)+";"
                        c.execute(query)
                        rowc = c.fetchone()
                        c.close()
                        if rowc:
                                logger.info(character_name + " is flagged as an fc - adding to fc group.")
                                c = sqdb.cursor()
                                query = "insert into group_members values ("
                                query += "(select group_id from groups where name=\'fc\' and channel_id=0),"
                                query += "1,"+str(character_id)+",1);"
                                c.execute(query)
                                sqdb.commit()
                                
			#CLose the sqlite db once we're done
			sqdb.close()
			
		except Exception as e:
			logger.error("Problem adding Mumble Group Privs")
			logger.error(str(e))
		logger.info("Mumble group privs added.")
# --- DOne

		self.logger.info(("Success: '{0}' as '{1}' in {2}").format(character_id, nick, groups))
		return (character_id, nick, groups)

	    except Exception, e:
		self.logger.error(("Fail: {0}".format(e)))
		return (-1, None, None)
	    finally:
		if db:
		    db.close()

	def createChannel(name, server, id):
		return -2

	def getRegistration(self, id, current=None):
	    return (-2, None, None)

	def registerPlayer(self, name, current=None):
	    self.logger.warn( ("Warn: Somebody tried to register player '{0}'").format(name))
	    return -1

	def unregisterPlayer(self, id, current=None):
	    self.logger.warn( ("Warn: Somebody tried to unregister player '{0}'").format(id))
	    return -1

	def getRegisteredUsers(self, filter, current=None):
	    return dict()

	def registerUser(self, name, current = None):
	    self.logger.warn( ("Warn: Somebody tried to register user '{0}'").format(name))
	    return -1

	def unregisterUser(self, name, current = None):
	    self.logger.warn( ("Warn: Somebody tried to unregister user '{0}'").format(name))
	    return -1

	def idToTexture(self, id, current=None):
		return None

	def idToName(self, id, current=None):
		return None

	def nameToId(self, name, current=None):
		return id

	def getInfo(self, id, current = None):
		return (False, None)

	def setInfo(self, id, info, current = None):
	    self.logger.warn( ("Warn: Somebody tried to set info for '{0}'").format(id))
	    return -1

	def setTexture(self, id, texture, current = None):
	    self.logger.warn( ("Warn: Somebody tried to set a texture for '{0}'").format(id))
	    return -1

# -------------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info('Starting authenticator...')

    ice = Ice.initialize(sys.argv)
    meta = Murmur.MetaPrx.checkedCast(ice.stringToProxy('Meta:tcp -h 127.0.0.1 -p 6502'))
    adapter = ice.createObjectAdapterWithEndpoints("Callback.Client", "tcp -h 127.0.0.1")
    adapter.activate()

    for server in meta.getBootedServers():
		if(server.id() != server_id):
			continue

		logger.info("Binding to server: {0} {1}".format(id, server))
		serverR = Murmur.ServerUpdatingAuthenticatorPrx.uncheckedCast(adapter.addWithUUID(ServerAuthenticatorI(server, adapter)))
		logger.info("Created server.")
		server.setAuthenticator(serverR)
		logger.info("Set server authenticator.")
		break
    try:
        ice.waitForShutdown()
    except KeyboardInterrupt:
        logger.info( 'Aborting!')

    ice.shutdown()
    logger.info( '7o' )
