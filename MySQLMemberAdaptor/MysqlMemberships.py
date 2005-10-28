# Copyright (C) 2001-2003 by the Free Software Foundation, Inc.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

"""Mysql Mailman membership adaptor.

This adaptor gets and sets member information on the MailList object given to
the constructor.  It also equates member keys and lower-cased email addresses,
i.e. KEY is LCE.

This adaptor is based upon the OldStyleMemberships adaptor, but incorporates
facilities to access the Membership data from a MySQL database.

Requires the MYSQLdb module.

Kev Green, oRe Net (http://www.orenet.co.uk/), 2003/11/04
$Revision: 1.61 $

"""

import time, sys
from types import StringType
from Mailman.Logging.Syslog import syslog

from Mailman import mm_cfg
from Mailman import Utils
from Mailman import Errors
from Mailman import MemberAdaptor
from Mailman.Bouncer import _BounceInfo

import MySQLdb 

# MySQL -> Python type coercing.
from MySQLdb.constants import FIELD_TYPE
_type_conv = { FIELD_TYPE.TINY: int,
               FIELD_TYPE.SHORT: int,
               FIELD_TYPE.LONG: long,
               FIELD_TYPE.FLOAT: float,
               FIELD_TYPE.DOUBLE: float,
               FIELD_TYPE.LONGLONG: long,
               FIELD_TYPE.INT24: int,
               FIELD_TYPE.YEAR: int }

ISREGULAR = 1
ISDIGEST = 2

# XXX check for bare access to mlist.members, mlist.digest_members,
# mlist.user_options, mlist.passwords, mlist.topics_userinterest

# XXX Fix Errors.MMAlreadyAMember and Errors.NotAMember
# Actually, fix /all/ errors



class MysqlMemberships(MemberAdaptor.MemberAdaptor):
    def __init__(self, mlist):
        self.__mlist = mlist
	# Check if we can access the database with a ping() call, so we error
	# out sooner rather than later because of it.
	try:
       		connection=MySQLdb.connect(passwd=mm_cfg.MYSQL_MEMBER_DB_PASS,
			db=mm_cfg.MYSQL_MEMBER_DB_NAME,
			user=mm_cfg.MYSQL_MEMBER_DB_USER,
			host=mm_cfg.MYSQL_MEMBER_DB_HOST) 
		connection.ping()
	except MySQLdb.OperationalError, e:
		# Connect failed.
	        syslog("error", "Fatal rror connecting to MySQL database %s (%s): %s" % (mm_cfg.MYSQL_MEMBER_DB_NAME, e.args[0], e.args[1]) )
	        print "Fatal error connecting to MySQL database %s (%s): %s" % (mm_cfg.MYSQL_MEMBER_DB_NAME, e.args[0], e.args[1]) 
                sys.exit(1)
	except MySQLdb.Warning, e:
		# Ping failed.
		syslog("error", "Fatal error PINGing MySQL database %s (%s): %s" % (mm_cfg.MYSQL_MEMBER_DB_NAME, e.args[0], e.args[1]) )
		print "Fatal error PINGing MySQL database %s (%s): %s" % (mm_cfg.MYSQL_MEMBER_DB_NAME, e.args[0], e.args[1]) 
		sys.exit(1)
	self.cursor = connection.cursor ()

	# To make sure we always have the table we need...
        self._prodServerConnection
	if self.getTableType is 'flat':
		self.cursor.execute ("""CREATE TABLE IF NOT EXISTS mailman_mysql (
  listname varchar(255) NOT NULL,
  address varchar(255) NOT NULL,
  hide enum('Y','N') NOT NULL default 'N',
  nomail enum('Y','N') NOT NULL default 'N',
  ack enum('Y','N') NOT NULL default 'Y',
  not_metoo enum('Y','N') NOT NULL default 'Y',
  digest enum('Y','N') NOT NULL default 'N',
  plain enum('Y','N') NOT NULL default 'N',
  password varchar(255) NOT NULL default '!',
  lang varchar(255) NOT NULL default 'en',
  name varchar(255) default NULL,
  one_last_digest enum('Y','N') NOT NULL default 'N',
  user_options bigint(20) NOT NULL default 0,
  delivery_status INT(10) NOT NULL default 0,
  topics_userinterest varchar(255) default NULL,
  delivery_status_timestamp datetime default '0',
  bi_cookie varchar(255) default NULL,
  bi_score double NOT NULL default '0',
  bi_noticesleft double NOT NULL default '0',
  bi_lastnotice date NOT NULL default '0000-00-00',
  bi_date date NOT NULL default '0000-00-00',
  PRIMARY KEY  (listname, address)
) TYPE=MyISAM""" )
	else:
		self.cursor.execute ("""CREATE TABLE IF NOT EXISTS %s (
  address varchar(255) NOT NULL,
  hide enum('Y','N') NOT NULL default 'N',
  nomail enum('Y','N') NOT NULL default 'N',
  ack enum('Y','N') NOT NULL default 'Y',
  not_metoo enum('Y','N') NOT NULL default 'Y',
  digest enum('Y','N') NOT NULL default 'N',
  plain enum('Y','N') NOT NULL default 'N',
  password varchar(255) NOT NULL default '!',
  lang varchar(255) NOT NULL default 'en',
  name varchar(255) default NULL,
  one_last_digest enum('Y','N') NOT NULL default 'N',
  user_options bigint(20) NOT NULL default 0,
  delivery_status int(10) NOT NULL default 0,
  topics_userinterest varchar(255) default NULL,
  delivery_status_timestamp datetime DEFAULT '0',
  bi_cookie varchar(255) default NULL,
  bi_score double NOT NULL default '0',
  bi_noticesleft double NOT NULL default '0',
  bi_lastnotice date NOT NULL default '0000-00-00',
  bi_date date NOT NULL default '0000-00-00',
  PRIMARY KEY  (address)
) TYPE=MyISAM""" %( self.__mlist.internal_name() ))

	try:
	   if mm_cfg.MYSQL_MEMBER_DB_VERBOSE:
		# Message to indicate successful init.
		syslog("error", "MysqlMemberships $Revision: 1.61 $ initialized with host: %s (%s)" % ( connection.get_host_info(), connection.get_server_info() ) )
	except AttributeError:
		pass

	# Remove the unused parts of the mailing list that we don't want from
	# the normal code (Borrowed from BDBMemberAdaptor)
        try:
                del mlist.members
                del mlist.digest_members
                del mlist.passwords
                del mlist.language
                del mlist.user_options
                del mlist.usernames
                del mlist.topics_userinterest
                del mlist.delivery_status
                del mlist.bounce_info
        except AttributeError:
                pass

    def __del__(self):
        # Cleaning up
	self.cursor.close()
	self.conn.close()
	try:
	   if mm_cfg.MYSQL_MEMBER_DB_VERBOSE:
		# Message to indicate successful close.
		syslog("error", "MysqlMemberships $Revision: 1.61 $ unloaded" )
           pass
	except AttributeError:
		pass

    # Find out whether we should be using 'flat' or 'wide' table type.
    # for backwards compatibility, the default is 'wide'
    def getTableType():
	if mm_cfg.MYSQL_MEMBER_TABLE_TYPE:
		if mm_cfg.MYSQL_MEMBER_TABLE_TYPE is 'flat':
			return 'flat'
		else:
			return 'wide'
	else:
    		return 'wide'
    #
    # Read interface
    #
    # SELECT address FROM <listname>
    def getMembers(self):
        self._prodServerConnection
	if self.getTableType is 'flat':
		self.cursor.execute ("SELECT address FROM mailman_mysql WHERE listname='%s'" %( self.__mlist.internal_name() ) )
	else:
		self.cursor.execute ("SELECT address FROM %s" %( self.__mlist.internal_name() ) )
	# get the number of rows in the resultset
	numrows = int(self.cursor.rowcount)
	# save one address at a time
	members = []
	for x in range(0,numrows):
		row = self.cursor.fetchone()
		members.append(row[0])
	return members

    # SELECT address FROM <listname> WHERE digest = "N"
    def getRegularMemberKeys(self):
        self._prodServerConnection
	if self.getTableType is 'flat':
		self.cursor.execute("SELECT address FROM mailman_mysql WHERE digest = 'N' AND listname='%s'" % (self.__mlist.internal_name()) )
	else:
		self.cursor.execute("SELECT address FROM %s WHERE digest = 'N'" % (self.__mlist.internal_name()) )
	# get the number of rows in the resultset
	numrows = int(self.cursor.rowcount)
	# save one address at a time
	members = []
	for x in range(0,numrows):
		row = self.cursor.fetchone()
		members.append(row[0])
	return members

    # SELECT address FROM <listname> WHERE digest = "Y"
    def getDigestMemberKeys(self):
        self._prodServerConnection
	if self.getTableType is 'flat':
		self.cursor.execute ("SELECT address FROM mailman_mysql WHERE digest = 'Y' AND listname='%s'"
			% ( self.__mlist.internal_name()))
	else:
		self.cursor.execute ("SELECT address FROM %s WHERE digest = 'Y'" 
			% ( self.__mlist.internal_name()))
	# get the number of rows in the resultset
	numrows = int(self.cursor.rowcount)
	# save one address at a time
	members = []
	for x in range(0,numrows):
		row = self.cursor.fetchone()
		members.append(row[0])
	return members

    def __get_cp_member(self, member):
        lcmember = member.lower()
        missing = []
        self._prodServerConnection
	if self.getTableType is 'flat':
		self.cursor.execute ("SELECT digest FROM mailman_mysql WHERE listname='%s' AND address = '%s'" 
			%( self.__mlist.internal_name() , MySQLdb.escape_string(lcmember) ) )
	else:
		self.cursor.execute ("SELECT digest FROM %s WHERE address = '%s'" 
			%( self.__mlist.internal_name() , MySQLdb.escape_string(lcmember) ) )

	# get the number of rows in the resultset
	numrows = int(self.cursor.rowcount)
        if numrows is not 0:
		row = self.cursor.fetchone()
		val = row[0]
		if val is 'Y':
			return lcmember, ISDIGEST
		else:
			return lcmember, ISREGULAR
        return None, None
# What does this bit do???
#        if val is not missing:
#            if isinstance(val, StringType):
#                return val, ISREGULAR
#            else:
#                return lcmember, ISREGULAR

    def isMember(self, member):
        self._prodServerConnection
	if self.getTableType is 'flat':
		self.cursor.execute ("SELECT * FROM mailman_mysql WHERE listname='%s' AND address = '%s'" 
			%( self.__mlist.internal_name() , 
			MySQLdb.escape_string(member)) )
	else:
		self.cursor.execute ("SELECT * FROM %s WHERE address = '%s'" 
			%( self.__mlist.internal_name() , 
			MySQLdb.escape_string(member)) )

	# get the number of rows in the resultset
	numrows = int(self.cursor.rowcount)
        if numrows is not 0:
            return 1
        return 0

    # Covered by SQL __get_cp_member()
    def getMemberKey(self, member):
        cpaddr, where = self.__get_cp_member(member)
        if cpaddr is None:
            raise Errors.NotAMemberError, member
        return member.lower()

    # Covered by SQL __get_cp_member()
    def getMemberCPAddress(self, member):
        cpaddr, where = self.__get_cp_member(member)
        if cpaddr is None:
            raise Errors.NotAMemberError, member
        return cpaddr

    # Covered by SQL __get_cp_member()
    def getMemberCPAddresses(self, members):
        return [self.__get_cp_member(member)[0] for member in members]

    # SELECT password FROM <listname> WHERE address = member.lower()
    def getMemberPassword(self, member):
        self._prodServerConnection
	if self.getTableType is 'flat':
		self.cursor.execute ("SELECT password FROM mailman_mysql WHERE listname='%s' AND address = '%s'"
			%( self.__mlist.internal_name(),
			MySQLdb.escape_string(member) ) )
	else:
		self.cursor.execute ("SELECT password FROM %s WHERE address = '%s'"
			%( self.__mlist.internal_name(),
			MySQLdb.escape_string(member) ) )

	# get the number of rows in the resultset
	numrows = int(self.cursor.rowcount)
	row = self.cursor.fetchone()
  	password = row[0]
        if password is None:
            raise Errors.NotAMemberError, member
        return password

    # Covered by SQL getMemberPassword()
    def authenticateMember(self, member, response):
        secret = self.getMemberPassword(member)
        if secret == response:
            return secret
        return 0

    # Covered by SQL isMember()
    def __assertIsMember(self, member):
        if not self.isMember(member):
            raise Errors.NotAMemberError, member

    def getMemberLanguage(self, member):
        self._prodServerConnection
	try:
		if self.getTableType is 'flat':
	   		self.cursor.execute("SELECT lang FROM mailman_mysql WHERE listname='%s' AND address = '%s'"
			%( self.__mlist.internal_name(),
			MySQLdb.escape_string(member) ) )
		else:
	   		self.cursor.execute("SELECT lang FROM %s WHERE address = '%s'"
			%( self.__mlist.internal_name(),
			MySQLdb.escape_string(member) ) )

	# This has been causing "MySQL has gone away errors".. :(
	except MySQLdb.OperationalError, e:
	   syslog("error", "MySQL SELECT warning (%s): %s, for address %s and list %s" % (e.args[0], e.args[1], member, self.__mlist.internal_name() ) )
	   return self.__mlist.preferred_language

	# get the number of rows in the resultset
	numrows = int(self.cursor.rowcount)
	# If we're looking up Lang for a non-member....
	if numrows < 1:
        	return self.__mlist.preferred_language
	# Otherwise.
	row = self.cursor.fetchone()
	lang = row[0]
        if lang in self.__mlist.GetAvailableLanguages():
            return lang
        return self.__mlist.preferred_language

    # SELECT digest FROM <listname> WHERE address = member.lower()
    def getMemberOption(self, member, flag):
        self.__assertIsMember(member)
        if flag == mm_cfg.Digests:
            cpaddr, where = self.__get_cp_member(member)
            return where == ISDIGEST
        self._prodServerConnection
	if self.getTableType is 'flat':
		self.cursor.execute("SELECT user_options FROM mailman_mysql WHERE listname='%s' AND address = '%s'" 
			% (self.__mlist.internal_name(), 
			MySQLdb.escape_string(member.lower())) )
	else:
		self.cursor.execute("SELECT user_options FROM %s WHERE address = '%s'" 
			% (self.__mlist.internal_name(), 
			MySQLdb.escape_string(member.lower())) )
	# save one address at a time
	row = self.cursor.fetchone()
	option = row[0]
        return not not (option & flag)

    def getMemberName(self, member):
        self.__assertIsMember(member)
        self._prodServerConnection
	if self.getTableType is 'flat':
		self.cursor.execute ("SELECT name FROM mailman_mysql WHERE listname='%s' AND address = '%s'"
			%( self.__mlist.internal_name(), 
			MySQLdb.escape_string(member) ) )
	else:
		self.cursor.execute ("SELECT name FROM %s WHERE address = '%s'"
			%( self.__mlist.internal_name(), 
			MySQLdb.escape_string(member) ) )
	row = self.cursor.fetchone()
  	name = row[0]
        return name

    def getMemberTopics(self, member):
        self.__assertIsMember(member)
        self._prodServerConnection
	if self.getTableType is 'flat':
		self.cursor.execute ("SELECT topics_userinterest FROM mailman_mysql WHERE listname = '%s' AND address = '%s'"
			%( self.__mlist.internal_name(), 
			MySQLdb.escape_string(member) ) )
	else:
		self.cursor.execute ("SELECT topics_userinterest FROM %s WHERE address = '%s'"
			%( self.__mlist.internal_name(), 
			MySQLdb.escape_string(member) ) )
	row = self.cursor.fetchone()
  	topics_userinterest = row[0]
	return topics_userinterest

    def getDeliveryStatus(self, member):
        self.__assertIsMember(member)
        self._prodServerConnection
	if self.getTableType is 'flat':
		self.cursor.execute ("SELECT delivery_status FROM mailman_mysql WHERE listname = '%s' AND address = '%s'"
			%( self.__mlist.internal_name(), 
			MySQLdb.escape_string(member) ) )
	else:
		self.cursor.execute ("SELECT delivery_status FROM %s WHERE address = '%s'"
			%( self.__mlist.internal_name(), 
			MySQLdb.escape_string(member) ) )
	row = self.cursor.fetchone()
  	delivery_status = row[0]
        if delivery_status in (MemberAdaptor.ENABLED,  MemberAdaptor.UNKNOWN,
                          MemberAdaptor.BYUSER,   MemberAdaptor.BYADMIN,
                          MemberAdaptor.BYBOUNCE):
		return delivery_status
	else:
		return MemberAdaptor.ENABLED

    def getDeliveryStatusChangeTime(self, member):
        self.__assertIsMember(member)
        self._prodServerConnection
	if self.getTableType is 'flat':
		self.cursor.execute("SELECT delivery_status_timestamp"
			" FROM mailman_mysql WHERE listname = '%s' AND address = '%s'"
			%( self.__mlist.internal_name() , 
			MySQLdb.escape_string(member) ) )
	else:
		self.cursor.execute("SELECT delivery_status_timestamp"
			" FROM %s WHERE address = '%s'"
			%( self.__mlist.internal_name() , 
			MySQLdb.escape_string(member) ) )
	row = self.cursor.fetchone()
  	delivery_status_timestamp = row[0]
	# I'm not sure if this is right...
	if delivery_status_timestamp is '0':
		return MemberAdaptor.ENABLED
	else:
		return delivery_status_timestamp

    # Covered by SQL getMembers(), and getDeliveryStatus().
    def getDeliveryStatusMembers(self, status=(MemberAdaptor.UNKNOWN,
                                               MemberAdaptor.BYUSER,
                                               MemberAdaptor.BYADMIN,
                                               MemberAdaptor.BYBOUNCE)):
        return [member for member in self.getMembers()
                if self.getDeliveryStatus(member) in status]

    def getBouncingMembers(self):
        self._prodServerConnection
	if self.getTableType is 'flat':
		self.cursor.execute ("""SELECT bi_cookie,bi_score,bi_noticesleft,
			UNIX_TIMESTAMP(bi_lastnotice),UNIX_TIMESTAMP(bi_date),address
				 FROM mailman_mysql
				 WHERE listname = '%s'"""
			% ( self.__mlist.internal_name()))
	else:
		self.cursor.execute ("""SELECT bi_cookie,bi_score,bi_noticesleft,
			UNIX_TIMESTAMP(bi_lastnotice),UNIX_TIMESTAMP(bi_date),address
				 FROM %s"""
			% ( self.__mlist.internal_name()))

	# get the number of rows in the resultset
	numrows = int(self.cursor.rowcount)
	# save one address at a time
	bounce_info_list = []
	for x in range(0,numrows):
		row = self.cursor.fetchone()
		# We must not return anything if there is
		# no bounce info for that member to start with.
		if row[4] > 0:
			# Append the member name to the bounce info list.
			bounce_info_list.append(row[5])
        return [member.lower() for member in bounce_info_list]

    def getBounceInfo(self, member):
        self.__assertIsMember(member)
        self._prodServerConnection
	if self.getTableType is 'flat':
		self.cursor.execute("""SELECT bi_cookie,
			bi_score,
			bi_noticesleft,
			YEAR(bi_lastnotice),
			MONTH(bi_lastnotice),
			DAYOFMONTH(bi_lastnotice),
			YEAR(bi_date),
			MONTH(bi_date),
			DAYOFMONTH(bi_date)
			FROM mailman_mysql
			WHERE listname='%s'
			AND address = '%s'"""
		%( self.__mlist.internal_name(), 
		MySQLdb.escape_string(member) ) )
	else:
		self.cursor.execute("""SELECT bi_cookie,
			bi_score,
			bi_noticesleft,
			YEAR(bi_lastnotice),
			MONTH(bi_lastnotice),
			DAYOFMONTH(bi_lastnotice),
			YEAR(bi_date),
			MONTH(bi_date),
			DAYOFMONTH(bi_date)
			FROM %s WHERE address = '%s'"""
		%( self.__mlist.internal_name(), 
		MySQLdb.escape_string(member) ) )
	numrows = int(self.cursor.rowcount)
	if numrows is 0:
		raise Errors.NotAMemberError, member
	row = self.cursor.fetchone()
	# We must not return a _BounceInfo instance if there is no bounce info
	# to start with.
	if row[4] <= 0:
		return None;
	# Otherwise, populate a bounce_info structure.
        bounce_info = _BounceInfo(member, row[1], (row[6],row[7],row[8]),
		row[2], row[0])
	bounce_info.lastnotice = (row[3],row[4],row[5])
        return bounce_info

    #
    # Write interface
    #
    def addNewMember(self, member, **kws):
        assert self.__mlist.Locked()
        # Make sure this address isn't already a member
        if self.isMember(member):
            raise Errors.MMAlreadyAMember, member
        # Parse the keywords
        digest = 0
        password = Utils.MakeRandomPassword()
        language = self.__mlist.preferred_language
        realname = None
        if kws.has_key('digest'):
            digest = kws['digest']
            del kws['digest']
        if kws.has_key('password'):
            password = kws['password']
            del kws['password']
        if kws.has_key('language'):
            language = kws['language']
            del kws['language']
        if kws.has_key('realname'):
            realname = kws['realname']
            del kws['realname']
        # Assert that no other keywords are present
        if kws:
            raise ValueError, kws.keys()
        # If the localpart has uppercase letters in it, then the value in the
        # members (or digest_members) dict is the case preserved address.
        # Otherwise the value is 0.  Note that the case of the domain part is
        # of course ignored.
        if Utils.LCDomain(member) == member.lower():
            value = 0
        else:
            value = member
            member = member.lower()
        if digest:
	    digest = 'Y'
        else:
	    digest = 'N'
        # All we need to do here is add the address.
        # and Set the member's default set of options: Using "0" for now, until
	# I work out a better way.
        self._prodServerConnection
	if self.getTableType is 'flat':
        	self.cursor.execute("""INSERT INTO mailman_mysql (listname,address,user_options,password,lang,digest,delivery_status) values ('%s','%s',0,'%s','%s','%s','%s')"""
			%( self.__mlist.internal_name() , MySQLdb.escape_string(member), password, language, digest, MemberAdaptor.UNKNOWN) )
	else:
        	self.cursor.execute("""INSERT INTO %s (address,user_options,password,lang,digest,delivery_status) values ('%s',0,'%s','%s','%s','%s')"""
			%( self.__mlist.internal_name() , MySQLdb.escape_string(member), password, language, digest, MemberAdaptor.UNKNOWN) )
        if realname:
            self.setMemberName(member, realname)

    def removeMember(self, member):
        assert self.__mlist.Locked()
        self.__assertIsMember(member)
        # Delete the appropriate entries from the various MailList attributes.
        # Remember that not all of them will have an entry (only those with
        # values different than the default).
        memberkey = member.lower()
        for attr in ('passwords', 'user_options', 'members', 'digest_members',
                     'language',  'topics_userinterest',     'usernames',
                     'bounce_info', 'delivery_status',
                     ):
            dict = getattr(self.__mlist, attr)
            if dict.has_key(memberkey):
                del dict[memberkey]
	# Not sure about whether we need to implement all of the above, but
	# from the SQL sense, this ought to do it.
        self._prodServerConnection
	if self.getTableType is 'flat':
        	self.cursor.execute("""DELETE FROM mailman_mysql WHERE listname = '%s' AND address = '%s'"""
			%( self.__mlist.internal_name() , memberkey) )
	else:
        	self.cursor.execute("""DELETE FROM %s WHERE address = '%s'"""
			%( self.__mlist.internal_name() , memberkey) )

    def changeMemberAddress(self, member, newaddress, nodelete=0):
        assert self.__mlist.Locked()
        # Make sure the old address is a member.  Assertions that the new
        # address is not already a member is done by addNewMember() below.
        self.__assertIsMember(member)

#	No need to faff with multiple lists here, just an SQL update will do
# 	the trick.
        self._prodServerConnection
	try:
		if self.getTableType is 'flat':
	        	self.cursor.execute(
				"""UPDATE mailman_mysql SET address = '%s'
				WHERE listname='%s' AND address = '%s'"""
				%( MySQLdb.escape_string(newaddress),
				 self.__mlist.internal_name() ,
				MySQLdb.escape_string(member) ) )
		else:
	        	self.cursor.execute("""UPDATE %s SET address = '%s'
				WHERE address = '%s'"""
				%( self.__mlist.internal_name() ,
				MySQLdb.escape_string(newaddress),
				MySQLdb.escape_string(member) ) )
	except MySQLdb.Warning, e:
		syslog("error", "MySQL update warning (%s): %s" % (e.args[0], e.args[1]) )

#        # Get the old values
#        memberkey = member.lower()
#        fullname = self.getMemberName(memberkey)
#        flags = self.__mlist.user_options.get(memberkey, 0)
#        digestsp = self.getMemberOption(memberkey, mm_cfg.Digests)
#        password = self.__mlist.passwords.get(memberkey,
#                                              Utils.MakeRandomPassword())
#        lang = self.getMemberLanguage(memberkey)
#        # First, possibly delete the old member
#        if not nodelete:
#            self.removeMember(memberkey)
#        # Now, add the new member
#        self.addNewMember(newaddress, realname=fullname, digest=digestsp,
#                          password=password, language=lang)
#        # Set the entire options bitfield
#        if flags:
#            self.__mlist.user_options[newaddress.lower()] = flags

    def setMemberPassword(self, memberkey, password):
        assert self.__mlist.Locked()
        self.__assertIsMember(memberkey)
        self._prodServerConnection
	try:
		if self.getTableType is 'flat':
        		self.cursor.execute("""UPDATE mailman_mysql SET password='%s'
				WHERE listname='%s' address = '%s'"""
			%( password, 
			 self.__mlist.internal_name() , 
			MySQLdb.escape_string(memberkey) ) )
		else:
        		self.cursor.execute("""UPDATE %s SET password='%s'
				WHERE address = '%s'"""
			%( self.__mlist.internal_name() , password, 
			MySQLdb.escape_string(memberkey) ) )
	except MySQLdb.Warning, e:
		syslog("error", "MySQL update warning setting password for member '%s'" % (member) )

    def setMemberLanguage(self, memberkey, language):
        assert self.__mlist.Locked()
        self.__assertIsMember(memberkey)
        self._prodServerConnection
	try:
		if self.getTableType is 'flat':
        		self.cursor.execute("""UPDATE mailman_mysql SET lang='%s'
				WHERE listname='%s' AND address = '%s'"""
			%( language, 
			 self.__mlist.internal_name() , 
			MySQLdb.escape_string(memberkey)) )
		else:
        		self.cursor.execute("""UPDATE %s SET lang='%s'
				WHERE address = '%s'"""
			%( self.__mlist.internal_name() , language, 
			MySQLdb.escape_string(memberkey)) )
	except MySQLdb.Warning, e:
		syslog("error", "MySQL update warning setting language for member '%s'" % (member) )


    def setMemberOption(self, member, flag, value):
        assert self.__mlist.Locked()
        self.__assertIsMember(member)
        memberkey = member.lower()
        # There's one extra gotcha we have to deal with.  If the user is
        # toggling the Digests flag, then we need to move their entry from
        # mlist.members to mlist.digest_members or vice versa.  Blarg.  Do
        # this before the flag setting below in case it fails.
        if flag == mm_cfg.Digests:
            if value:
                # Be sure the list supports digest delivery
                if not self.__mlist.digestable:
                    raise Errors.CantDigestError
		# The user is turning on digest mode
        	self._prodServerConnection
		if self.getTableType is 'flat':
			self.cursor.execute ("SELECT digest "
				"FROM mailman_mysql"
				"WHERE listname='%s' AND address = '%s'"
				%( self.__mlist.internal_name(), 
				MySQLdb.escape_string(member) ) )
		else:
			self.cursor.execute ("SELECT digest "
				"FROM %s "
				"WHERE address = '%s'"
				%( self.__mlist.internal_name(), 
				MySQLdb.escape_string(member) ) )
		# get the number of rows in the resultset, error if none.
		numrows = int(self.cursor.rowcount)
                if numrows is 0:
                    raise Errors.NotAMemberError, member
		# Fetch the results to check if they are recieving digests.
		row = self.cursor.fetchone()
		digest = row[0]
		# If they are already receiving digests, report an error.
		if digest is 'Y':
                    raise Errors.AlreadyReceivingDigests, member
		# If we've got past all this, actually turn on digest mode.
		try:
        		self._prodServerConnection
			if self.getTableType is 'flat':
				self.cursor.execute("""UPDATE mailman_mysql SET digest='Y'
				WHERE listname='%s' AND address = '%s'"""
				%( self.__mlist.internal_name() ,
				MySQLdb.escape_string(memberkey) ) )
			else:
				self.cursor.execute("""UPDATE %s SET digest='Y'
				WHERE address = '%s'"""
				%( self.__mlist.internal_name() ,
				MySQLdb.escape_string(memberkey) ) )
		except MySQLdb.Warning, e:
			syslog("error", "MySQL update warning (%s): %s" % (e.args[0], e.args[1]) )
            else:
                # Be sure the list supports regular delivery
                if not self.__mlist.nondigestable:
                    raise Errors.MustDigestError
                # The user is turning off digest mode
        	self._prodServerConnection
		if self.getTableType is 'flat':
			self.cursor.execute ("SELECT digest "
				"FROM mailman_mysql "
				"WHERE listname='%s' AND address = '%s'"
				%( self.__mlist.internal_name(), 
				MySQLdb.escape_string(member) ) )
		else:
			self.cursor.execute ("SELECT digest "
				"FROM %s "
				"WHERE address = '%s'"
				%( self.__mlist.internal_name(), 
				MySQLdb.escape_string(member) ) )
		# get the number of rows in the resultset, error if none.
		numrows = int(self.cursor.rowcount)
                if numrows is 0:
                    raise Errors.NotAMemberError, member
		# Fetch the results to check if they are recieving digests.
		row = self.cursor.fetchone()
		digest = row[0]
		# If they are already receiving digests, report an error.
		if digest is 'N':
                    raise Errors.AlreadyReceivingRegularDeliveries, member
		# If we've got past all this, actually turn off digest mode,
		# and set the one_last_digest flag, so they don't loose any 
		# mail.
		try:
        		self._prodServerConnection
			if self.getTableType is 'flat':
				self.cursor.execute("""UPDATE mailman_mysql SET digest='N',
					one_last_digest='Y'
					WHERE listname='%s' AND address = '%s'"""
				%( self.__mlist.internal_name() , 
				MySQLdb.escape_string(memberkey) ) )
			else:
				self.cursor.execute("""UPDATE %s SET digest='N',
					one_last_digest='Y'
					WHERE address = '%s'"""
				%( self.__mlist.internal_name() , 
				MySQLdb.escape_string(memberkey) ) )
		except MySQLdb.Warning, e:
			syslog("error", "MySQL update warning (%s): %s" % (e.args[0], e.args[1]) )
            # We don't need to touch user_options because the digest state
            # isn't kept as a bitfield flag.
            return
        # This is a bit kludgey because the semantics are that if the user has
        # no options set (i.e. the value would be 0), then they have no entry
        # in the user_options dict.  We use setdefault() here, and then del
        # the entry below just to make things (questionably) cleaner.
#        self.__mlist.user_options.setdefault(memberkey, 0)
#        if value:
#            self.__mlist.user_options[memberkey] |= flag
#        else:
#            self.__mlist.user_options[memberkey] &= ~flag
#        if not self.__mlist.user_options[memberkey]:
#            del self.__mlist.user_options[memberkey]
#
# Apparently, mysql supports the & and | operators, so this should work, maybe.
# will have to suck it and see for the moment.
	# If the value is non-zero, set the bitfield indicated by 'flag'.
	if value:
		try:
        		self._prodServerConnection
			if self.getTableType is 'flat':
				self.cursor.execute( """UPDATE mailman_mysql
				SET user_options = user_options | %s
				WHERE listname = '%s' AND address = '%s'"""
				%( flag,
				 self.__mlist.internal_name() ,
				MySQLdb.escape_string(memberkey) ) )
			else:
				self.cursor.execute( """UPDATE %s
				SET user_options = user_options | %s
				WHERE address = '%s'"""
				%( self.__mlist.internal_name() , flag,
				MySQLdb.escape_string(memberkey) ) )
		except MySQLdb.Warning, e:
			syslog("error", "MySQL update warning (%s): %s" % (e.args[0], e.args[1]) )
	else:
		# Otherwise, unset it...
		try:
        		self._prodServerConnection
			if self.getTableType is 'flat':
        			self.cursor.execute("""UPDATE mailman_mysql 
					SET user_options = user_options & ~%s
					WHERE listname = '%s' AND address = '%s'"""
				%( flag,
				self.__mlist.internal_name() ,
				MySQLdb.escape_string(memberkey) ) )
			else:
        			self.cursor.execute("""UPDATE %s 
					SET user_options = user_options & ~%s
					WHERE address = '%s'"""
				%( self.__mlist.internal_name() , flag,
				MySQLdb.escape_string(memberkey) ) )
		except MySQLdb.Warning, e:
			syslog("error", "MySQL update warning (%s): %s" % (e.args[0], e.args[1]) )

    def setMemberName(self, member, realname):
        assert self.__mlist.Locked()
        self.__assertIsMember(member)
        self._prodServerConnection
	try:
		if self.getTableType is 'flat':
        		self.cursor.execute("""UPDATE mailman_mysql SET name='%s'
				WHERE address = '%s' AND listname = '%s'"""
			%( MySQLdb.escape_string(realname),
			MySQLdb.escape_string(member) ,
			self.__mlist.internal_name())
			)
		else:
        		self.cursor.execute("""UPDATE %s SET name='%s'
				WHERE address = '%s'"""
			%( self.__mlist.internal_name(),
			MySQLdb.escape_string(realname),
			MySQLdb.escape_string(member) ) )
	except MySQLdb.Warning, e:
		syslog("error", "MySQL update warning (%s): %s" % (e.args[0], e.args[1]) )

    def setMemberTopics(self, member, topics):
        assert self.__mlist.Locked()
        self.__assertIsMember(member)
        memberkey = member.lower()
        self._prodServerConnection
	try:
		if self.getTableType is 'flat':
        		self.cursor.execute("""UPDATE mailman_mysql SET topics_userinterest='%s'
				WHERE listname='%s' AND address = '%s'"""
			%( topics,
			self.__mlist.internal_name() ,
			MySQLdb.escape_string(member) ) )
		else:
        		self.cursor.execute("""UPDATE %s SET topics_userinterest='%s'
				WHERE address = '%s'"""
			%( self.__mlist.internal_name() , topics,
			MySQLdb.escape_string(member) ) )
	except MySQLdb.Warning, e:
		syslog("error", "MySQL update warning setting topics_userinterest for member %s" % (member) )

    def setDeliveryStatus(self, member, status):
        assert status in (MemberAdaptor.ENABLED,  MemberAdaptor.UNKNOWN,
                          MemberAdaptor.BYUSER,   MemberAdaptor.BYADMIN,
                          MemberAdaptor.BYBOUNCE)
        assert self.__mlist.Locked()
        self.__assertIsMember(member)
        member = member.lower()
        if status == MemberAdaptor.ENABLED:
            # Enable by resetting their bounce info.
            self.setBounceInfo(member, None)
        else:
        	self._prodServerConnection
		try:
			if self.getTableType is 'flat':
      				self.cursor.execute("""UPDATE mailman_mysql 
				SET delivery_status='%s',
				delivery_status_timestamp=NOW()
				WHERE address = '%s'
				AND listname='%s'"""
				%( status, 
				MySQLdb.escape_string(member),
				self.__mlist.internal_name()) )
			else:
      				self.cursor.execute("""UPDATE %s 
				SET delivery_status='%s',
				delivery_status_timestamp=NOW()
				WHERE address = '%s'"""
				%( self.__mlist.internal_name() ,
				status, 
				MySQLdb.escape_string(member)) )
		except MySQLdb.Warning, e:
			syslog("error", "MySQL update warning setting Delivery Status info to '%s' for member '%s'" % (status, member) )

    def setBounceInfo(self, member, info):
        assert self.__mlist.Locked()
        self.__assertIsMember(member)
        member = member.lower()
        if info is None:
		try:
        		self._prodServerConnection
			if self.getTableType is 'flat':
            			self.cursor.execute("""UPDATE mailman_mysql SET 
				bi_cookie = NULL,
				bi_score = 0,
                	        bi_noticesleft = 0,
				bi_lastnotice = '0000-00-00',
	                        bi_date = '0000-00-00'
				WHERE listname = '%s'
				AND address = '%s'"""
				%( self.__mlist.internal_name() , 
				MySQLdb.escape_string(member) ) )
			else:
            			self.cursor.execute("""UPDATE %s SET 
				bi_cookie = NULL,
				bi_score = 0,
                	        bi_noticesleft = 0,
				bi_lastnotice = '0000-00-00',
	                        bi_date = '0000-00-00'
				WHERE address = '%s'"""
				%( self.__mlist.internal_name() , 
				MySQLdb.escape_string(member) ) )
		except MySQLdb.Warning, e:
			syslog("error", "MySQL update warning setting Bounce info for member '%s'" % (member) )
		try:
        		self._prodServerConnection
			if self.getTableType is 'flat':
            			self.cursor.execute("""UPDATE mailman_mysql 
				SET delivery_status = '%s'
				WHERE listname = '%s' AND address = '%s'"""
				%( MemberAdaptor.ENABLED,
				 self.__mlist.internal_name() ,
				MySQLdb.escape_string(member) ) )
			else:
            			self.cursor.execute("""UPDATE %s 
				SET delivery_status = '%s'
				WHERE address = '%s'"""
				%( self.__mlist.internal_name() ,
				MemberAdaptor.ENABLED,
				MySQLdb.escape_string(member) ) )
		except MySQLdb.Warning, e:
			syslog("error", "MySQL update warning setting Delivery Status info to '%s' for member '%s' in setBounceInfo()" % (status, member) )
        else:
            self._prodServerConnection
	    try:
			# Hack the dates to work with MySQL.
			lnsql=(info.lastnotice[0],info.lastnotice[1],info.lastnotice[2],0,0,0,0,0,0)
			lnsql = time.strftime("%Y-%m-%d", lnsql)
			datesql = (info.date[0],info.date[1],info.date[2],0,0,0,0,0,0)
			datesql = time.strftime("%Y-%m-%d",datesql)
			if self.getTableType is 'flat':
            			self.cursor.execute("""UPDATE mailman_mysql SET 
				bi_cookie = '%s',
				bi_score = %s,
                	        bi_noticesleft = %s,
				bi_lastnotice = '%s',
	                        bi_date = '%s'
				WHERE address = '%s'
				AND listname = '%s'"""
				%( info.cookie,
				info.score, info.noticesleft,
				lnsql, datesql,
				MySQLdb.escape_string(member),
				self.__mlist.internal_name()
				) )
			else:
            			self.cursor.execute("""UPDATE %s SET 
				bi_cookie = '%s',
				bi_score = %s,
                	        bi_noticesleft = %s,
				bi_lastnotice = '%s',
	                        bi_date = '%s'
				WHERE address = '%s'"""
				%( self.__mlist.internal_name() , info.cookie,
				info.score, info.noticesleft,
				lnsql, datesql,
				MySQLdb.escape_string(member) ) )
	    except MySQLdb.Warning, e:
			syslog("error", "MySQL update warning setting bounce info for member %s" % (member) )

    # Check to see if a connection's still alive. If not, reconnect.
    def _prodServerConnection():
	alive = ping(self.connection)
        if alive == 0:
	    # Connection alive, or reconnected ok by ping()
            return self.connection
	else:
	   try:
              # Connection failed, or an error, try a hard dis+reconnect.
	      self.cursor.close()
	      self.connection.close()
              self.connection=MySQLdb.connect(passwd=mm_cfg.MYSQL_MEMBER_DB_PASS,
		db=mm_cfg.MYSQL_MEMBER_DB_NAME,user=mm_cfg.MYSQL_MEMBER_DB_USER,
		host=mm_cfg.MYSQL_MEMBER_DB_HOST) 
	   except MySQLdb.Warning, e:
	      syslog("error", "Error reconnecting to MySQL database %s (%s): %s" % (mm_cfg.MYSQL_MEMBER_DB_NAME, e.args[0], e.args[1]) )
	      sys.exit(1)
	return self.connection

