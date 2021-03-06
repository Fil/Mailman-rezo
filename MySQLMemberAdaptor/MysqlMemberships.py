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

Extensively modified by Fil <fil@rezo.net>, 2005/11/01

based on Kev's $Revision: 1.69 $

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

ISREGULAR = 1
ISDIGEST = 2
tm_min = 4

mm_cfg.connection = 0
mm_cfg.cursor = 0

try:
    mm_cfg.MYSQL_MEMBER_DB_VERBOSE
except AttributeError:
    mm_cfg.MYSQL_MEMBER_DB_VERBOSE = False  # default value
    pass



class MysqlMemberships(MemberAdaptor.MemberAdaptor):

    def __init__(self, mlist):
        self.__mlist = mlist
        self._dbconnect()

        # define the table and standard condition reflecting listname
        # (this is for upwards compatibility with the 'wide' mode and
        # the formerly fixed name of database table in 'flat' mode)
        if self.getTableType() is 'flat':
            try:
                self._table = mm_cfg.MYSQL_MEMBER_TABLE_NAME
            except AttributeError:
                self._table = 'mailman_mysql'
            self._where = "listname = '%s'" %(self.__mlist.internal_name())
        else:
            self._table = self.__mlist.internal_name()
            self._where = '1=1'

        # Make sure we always have the table we need...
        # if mm_cfg.MYSQL_MEMBER_CREATE_TABLE was defined
        try:
            if mm_cfg.MYSQL_MEMBER_CREATE_TABLE:
                self.createTable()
        except AttributeError:
            pass

        if mm_cfg.MYSQL_MEMBER_DB_VERBOSE:
            # Message to indicate successful init.
            message = "MysqlMemberships " \
                + "$Revision: 1.69 $ initialized with host: %s (%s)" % (
                mm_cfg.connection.get_host_info(),
                mm_cfg.connection.get_server_info() )
            syslog('error', message)
            syslog('mysql', message)

        # add a cache memory
        self._cache = {}
        self._cachedate = 0


    def __del__(self):
        # Cleaning up
        try:
            mm_cfg.cursor.close()
        except:
            pass
        try:
            mm_cfg.connection.close()
        except:
            pass
        if mm_cfg.MYSQL_MEMBER_DB_VERBOSE:
            # Message to indicate successful close.
            syslog("error", "MysqlMemberships $Revision: 1.69 $ unloaded" )
            syslog("mysql", "MysqlMemberships $Revision: 1.69 $ unloaded" )

    # Find out whether we should be using 'flat' or 'wide' table type.
    # for backwards compatibility, the default is 'wide'
    def getTableType(me):
        if mm_cfg.MYSQL_MEMBER_TABLE_TYPE:
            if mm_cfg.MYSQL_MEMBER_TABLE_TYPE is 'flat':
                return 'flat'
            else:
                return 'wide'
        else:
            return 'wide'

    # Check to see if a connection's still alive. If not, reconnect.
    def _dbconnect(self):
        if mm_cfg.connection:
            try:
                if mm_cfg.connection.ping() == 0:
                    return mm_cfg.connection
            except:
                syslog('mysql', 'connection warning')
                pass

            # Connection failed, or an error, try a hard dis+reconnect.
            try:
                mm_cfg.cursor.close()
            except:
                syslog('error', 'error on mm_cfg.cursor.close()')
                pass

            try:
                mm_cfg.connection.close()
            except:
                syslog('error', 'error on mm_cfg.connection.close()')
                pass

        try:
            mm_cfg.connection = MySQLdb.connect(
                passwd=mm_cfg.MYSQL_MEMBER_DB_PASS,
                db=mm_cfg.MYSQL_MEMBER_DB_NAME,
                user=mm_cfg.MYSQL_MEMBER_DB_USER,
                host=mm_cfg.MYSQL_MEMBER_DB_HOST)
            mm_cfg.cursor = mm_cfg.connection.cursor()
        except MySQLdb.OperationalError, e:
            message = "Error connecting to MySQL database %s (%s): %s" %(
                    mm_cfg.MYSQL_MEMBER_DB_NAME, e.args[0], e.args[1])
            syslog('error', message)
            if mm_cfg.MYSQL_MEMBER_DB_VERBOSE:
                syslog('mysql', message)
            # exit? why not sleep(30) and retry?
            sys.exit(1)

        return mm_cfg.connection



    # create tables (if the option is set in mm_cfg)
    def createTable(self):
        if self.getTableType() is 'flat':
            self.query (
"""CREATE TABLE IF NOT EXISTS `%s` (
  listname varchar(100) NOT NULL,
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
  delivery_status_timestamp datetime default '0000-00-00 00:00:00',
  bi_cookie varchar(255) default NULL,
  bi_score double NOT NULL default '0',
  bi_noticesleft double NOT NULL default '0',
  bi_lastnotice date NOT NULL default '0000-00-00',
  bi_date date NOT NULL default '0000-00-00',
  PRIMARY KEY  (listname, address)
) ENGINE=MyISAM""" %(self._table))
        else:
            self.query (
"""CREATE TABLE IF NOT EXISTS `%s` (
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
  delivery_status_timestamp datetime DEFAULT '0000-00-00 00:00:00',
  bi_cookie varchar(255) default NULL,
  bi_score double NOT NULL default '0',
  bi_noticesleft double NOT NULL default '0',
  bi_lastnotice date NOT NULL default '0000-00-00',
  bi_date date NOT NULL default '0000-00-00',
  PRIMARY KEY  (address)
) ENGINE=MyISAM""" %(self._table))


    # empty the cache (when we touch a value)
    def uncache(self):
        self._cache = {}
        self._cachedate = time.localtime()[tm_min]

    # Apply query on list (manages both 'flat' and 'wide' modes)
    def query(self, query):
        if mm_cfg.MYSQL_MEMBER_DB_VERBOSE:
            syslog('mysql', query)
        self._dbconnect()
        return mm_cfg.cursor.execute (query)

    # return all members according to a certain condition
    def queryall(self, query, cache=False):
        self.query(query)
        # get the number of rows in the resultset
        numrows = int(mm_cfg.cursor.rowcount)
        # save one at a time
        results = []
        for x in range(0,numrows):
            row = mm_cfg.cursor.fetchone()
            results.append(row[0])
            # we don't want to cache the whole list for global requests
            if cache and numrows < 1000:
                self._cache[row[1]] = row[2:]
        return results

    # select *, cache it, then return only the field that's asked for
    def select(self, what, where=''):
        query = "SELECT " + what \
            + ",address,name,user_options,delivery_status,lang,digest " \
            + "FROM `%s` WHERE %s" %(self._table, self._where)
        if where:
            query += " AND %s" %(where)
        return self.queryall(query + ' ORDER BY address', True)

    def select_on(self, what, address):
        if self._cachedate != time.localtime()[tm_min]:
            self.uncache()
        try:
            a = self._cache[address]
            if what == 'name':
                num = 0
            elif what == 'user_options':
                num = 1
            elif what == 'delivery_status':
                num = 2
            elif what == 'lang':
                num = 3
            elif what == 'digest':
                num = 4
            a = [ a[num] ]
        except:
            a = self.select(what,
                "address='%s'" %(self.escape(address)))
        return a

    def update_on(self, what, value, address):
        if what == 'delivery_status':
            dst = ", delivery_status_timestamp=NOW() "
        else:
            dst = ""
        self.query("UPDATE `%s` " %(self._table)
                + ("SET %s = '%s' " %(what, self.escape(value))
                + dst
                + ("WHERE %s " %(self._where))
                + ("AND address = '%s'" %(self.escape(address)))))
        # remove the cache
        self.uncache()

    def escape(self, value):
        # transforms accents into html entities (&#233;)
        # TODO: find out which language is current (here: assumes iso-8859-1)
        value = Utils.uncanonstr(value)

        # add slashes before " and '
        return MySQLdb.escape_string(value)


    ############################### Now the active codes #######
    #
    # Read interface
    #

    # All members
    def getMembers(self):
        return self.select('address')

    # regular members
    def getRegularMemberKeys(self):
        return self.select('address', "digest = 'N'")

    # digest members
    def getDigestMemberKeys(self):
        return self.select('address', "digest = 'Y'")

    # status (regular/digest) of a member (returns a key - lowercase)
    def __get_cp_member(self, member):
        lcmember = member.lower()
        digest = self.select_on('digest', lcmember)
        if len(digest):
            if digest is 'Y':
                return lcmember, ISDIGEST
            else:
                return lcmember, ISREGULAR
        return None, None

    # is she a member?
    def isMember(self, member):
        member = self.select_on('name', member)
        if len(member):
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
        password = self.select_on('password', member)
        if len(password):
            return password[0]
        else:
            raise Errors.NotAMemberError, member

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
        lang = self.select_on('lang',member)
        if len(lang) and lang[0] in self.__mlist.GetAvailableLanguages():
            return lang[0]
        else:
            return self.__mlist.preferred_language

    # getOptions: different methods for digest and other (bitfield) options
    def getMemberOption(self, member, flag):
        self.__assertIsMember(member)
        if flag == mm_cfg.Digests:
            cpaddr, where = self.__get_cp_member(member)
            return where == ISDIGEST
        options = self.select_on('user_options', member)
        if len(options):
            return not not (options[0] & flag)


    # new method to gest faster results when searching a user in the admin Gui
    def getMembersMatching(self, regexp):
        return self.select('address',
            "(address REGEXP '%s' OR name REGEXP '%s')"
            %( self.escape(regexp), self.escape(regexp) ) )

    # new method to get faster results when querying the number of subscribers
    def getMembersCount(self, reason=None):
        if reason:
            where = " AND digest='%s'" %reason
        else:
            where = ""
        self.query("SELECT COUNT(*) FROM `%s` WHERE %s%s" %(
          self._table, self._where, where))
        count = mm_cfg.cursor.fetchone()
        return int(count[0])

    # get member's name (slow method if you need many)
    # due to the way escape() is built, names are stored in html
    # format in the DB, hence the canonstr() to put them back to
    # normal (TODO)
    def getMemberName(self, member):
        name = self.select_on('name', member)
        if len(name):
          try:
            return Utils.canonstr(name[0])
          except:
            return name[0]
        self.__assertIsMember(member)

    # topics
    def getMemberTopics(self, member):
        topics = self.select_on('topics_userinterest',member)
        if len(topics) and isinstance(topics[0], str):
            return topics[0].split(',')
        return []
        self.__assertIsMember(member)

    # delivery status
    def getDeliveryStatus(self, member):
        status = self.select_on('delivery_status',member)
        if len(status):
            if status[0] in (MemberAdaptor.ENABLED, MemberAdaptor.UNKNOWN,
                          MemberAdaptor.BYUSER, MemberAdaptor.BYADMIN,
                          MemberAdaptor.BYBOUNCE):
                return status[0]
            else:
                return MemberAdaptor.ENABLED
        self.__assertIsMember(member)


    # delivery status change time
    def getDeliveryStatusChangeTime(self, member):
        time = self.select_on('delivery_status_timestamp',member)
        if len(time):
            time = time[0]
            if time is '0':
                return MemberAdaptor.ENABLED
            else:
                return time
        self.__assertIsMember(member)

    # Covered by SQL getMembers(), and getDeliveryStatus().
    def getDeliveryStatusMembers(self, status=(MemberAdaptor.UNKNOWN,
                                               MemberAdaptor.BYUSER,
                                               MemberAdaptor.BYADMIN,
                                               MemberAdaptor.BYBOUNCE)):
        return [member for member in self.getMembers()
                if self.getDeliveryStatus(member) in status]

    # show bouncing members
    def getBouncingMembers(self):
        self.query("""SELECT bi_cookie,bi_score,bi_noticesleft,
            UNIX_TIMESTAMP(bi_lastnotice),UNIX_TIMESTAMP(bi_date),address
            FROM `%s` WHERE %s""" %(self._table, self._where))
        # get the number of rows in the resultset
        numrows = int(mm_cfg.cursor.rowcount)
        # save one address at a time
        bounce_info_list = []
        for x in range(0,numrows):
            row = mm_cfg.cursor.fetchone()
            # We must not return anything if there is
            # no bounce info for that member to start with.
            if row[4] > 0:
                # Append the member name to the bounce info list.
                bounce_info_list.append(row[5])
        return [member.lower() for member in bounce_info_list]

    def getBounceInfo(self, member):
        self.query("""SELECT
            bi_score,
            bi_noticesleft,
            YEAR(bi_lastnotice),
            MONTH(bi_lastnotice),
            DAYOFMONTH(bi_lastnotice),
            YEAR(bi_date),
            MONTH(bi_date),
            DAYOFMONTH(bi_date),
            bi_cookie
            FROM `%s` WHERE %s AND """ %(self._table, self._where)
            + ("address = '%s'" %( self.escape(member) ) ))
        numrows = int(mm_cfg.cursor.rowcount)
        if numrows is 0:
            self.__assertIsMember(member)
        row = mm_cfg.cursor.fetchone()
        # We must not return a _BounceInfo instance if there is no bounce info
        # to start with.
        if row[3] <= 0:
            return None;
        # Otherwise, populate a bounce_info structure.
        bounce_info = _BounceInfo(member, row[0],
            (row[5],row[6],row[7]), row[1])
        bounce_info.lastnotice = (row[2],row[3],row[4])
        bounce_info.cookie = row[8]
        return bounce_info


    #
    # Write interface
    #
    def addNewMember(self, member, **kws):
#        assert self.__mlist.Locked()
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
        # and Set the member's default set of options
        if self.__mlist.new_member_options:
            options = self.__mlist.new_member_options
        else:
            options = 0
        if self.getTableType() is 'flat':
            query = "INSERT INTO `%s` " %(self._table) \
            + "(listname, address, user_options, password, lang, " \
            + "digest, delivery_status) values " \
            + "('%s','%s',%s,'%s','%s','%s','%s')"
        else:
            query = "INSERT INTO `%s` " \
            + "(address, user_options, password, lang, " \
            + "digest, delivery_status) values " \
            + "('%s',%s,'%s','%s','%s','%s')"
        query = query %( self.__mlist.internal_name(),
            self.escape(member), options, password,
            language, digest, MemberAdaptor.ENABLED)
        if mm_cfg.MYSQL_MEMBER_DB_VERBOSE:
            syslog('mysql',query)
        mm_cfg.cursor.execute(query)
        if realname:
            self.setMemberName(member, realname)

    def removeMember(self, member):
#        assert self.__mlist.Locked()
        self.__assertIsMember(member)
        self.query("DELETE FROM `%s` WHERE %s " %(self._table, self._where)
            + ("AND address = '%s'" %( self.escape(member.lower()) ) ))
        self.uncache()

    def changeMemberAddress(self, member, newaddress, nodelete=0):
#        assert self.__mlist.Locked()
        # Make sure this address isn't already a member
        if self.isMember(newaddress):
            raise Errors.MMAlreadyAMember, newaddress
        self.update_on('address', newaddress, member)

    def setMemberPassword(self, member, password):
#        assert self.__mlist.Locked()
        self.update_on('password', password, member)

    def setMemberLanguage(self, member, lang):
#        assert self.__mlist.Locked()
        self.update_on('lang', lang, member)

    def setMemberOption(self, member, flag, value):
#        assert self.__mlist.Locked()
        if flag == mm_cfg.Digests:
            if value:
                # Be sure the list supports digest delivery
                if not self.__mlist.digestable:
                    raise Errors.CantDigestError
                # The user is turning on digest mode
                # If they are already receiving digests, report an error.
                if self.getMemberOption(member, mm_cfg.Digests) is 'Y':
                    raise Errors.AlreadyReceivingDigests, member
                # If we've got past all this, actually turn on digest mode.
                self.update_on('digest', 'Y', member)
            else:
                # Be sure the list supports regular delivery
                if not self.__mlist.nondigestable:
                    raise Errors.MustDigestError
                # The user is turning off digest mode
                # If they are already receiving regular, report an error.
                if self.getMemberOption(member, mm_cfg.Digests) is 'N':
                    raise Errors.AlreadyReceivingRegularDeliveries, member
                # If we've got past all this, actually turn off digest mode.
                self.update_on('digest', 'N', member)
            return

        # Apparently, mysql supports the & and | operators, so this should
        # work, maybe. Will have to suck it and see for the moment.
        # If the value is non-zero, set the bitfield indicated by 'flag'.
        if value:
            self.query("UPDATE `%s` " %(self._table)
                + ("SET user_options = user_options | %s " %(flag))
                + "WHERE %s " %(self._where)
                + ("AND address = '%s'" %( self.escape(member) ) ))
        else:
            self.query("UPDATE `%s` " %(self._table)
                + ("SET user_options = user_options & ~%s " %(flag))
                + "WHERE %s " %(self._where)
                + ("AND address = '%s'" %( self.escape(member) ) ))
        # remove the cache
        self.uncache()

    def setMemberName(self, member, name):
#        assert self.__mlist.Locked()
        self.update_on('name', name, member)

    def setMemberTopics(self, member, topics):
#        assert self.__mlist.Locked()
        if isinstance(topics,list):
          topics=",".join(topics)
        else:
          topics=""
        self.query("UPDATE `%s` " %(self._table)
            + ("SET topics_userinterest = '%s' " %(
              self.escape(topics) ))
            + "WHERE %s " %(self._where)
            + ("AND address = '%s'" %( self.escape(member) )))

    def setDeliveryStatus(self, member, status):
        assert status in (MemberAdaptor.ENABLED,  MemberAdaptor.UNKNOWN,
                          MemberAdaptor.BYUSER,   MemberAdaptor.BYADMIN,
                          MemberAdaptor.BYBOUNCE)
#        assert self.__mlist.Locked()
        member = member.lower()
        if status == MemberAdaptor.ENABLED:
            # Enable by resetting their bounce info.
            self.setBounceInfo(member, None)
        else:
            self.query("UPDATE `%s` " %(self._table)
                + ("SET delivery_status = '%s', " %(status))
                + "delivery_status_timestamp=NOW() WHERE %s " %(self._where)
                + ("AND address = '%s'" %( self.escape(member) )))
        # remove the cache
        self.uncache()                                                

    def setBounceInfo(self, member, info):
#        assert self.__mlist.Locked()
        member = member.lower()
        if info is None:
            self.query("UPDATE `%s` " %(self._table)
                + ("SET delivery_status = '%s', " %(MemberAdaptor.ENABLED))
                + "bi_cookie = NULL, "
                + "bi_score = 0, "
                + "bi_noticesleft = 0, "
                + "bi_lastnotice = '0000-00-00', "
                + "bi_date = '0000-00-00' "
                + "WHERE %s " %(self._where)
                + ("AND address = '%s'" %( self.escape(member) )))
        else:
            # Hack the dates to work with MySQL.
            lnsql = time.strftime("%Y-%m-%d", time.strptime('-'.join(map(str,info.lastnotice)),'%Y-%m-%d'))
            datesql = time.strftime("%Y-%m-%d", time.strptime('-'.join(map(str,info.date)),'%Y-%m-%d'))
            self.query("UPDATE `%s` " %(self._table)
                + (("SET bi_cookie = '%s', "
                    + "bi_score = %s, "
                    + "bi_noticesleft = %s, "
                    + "bi_lastnotice = '%s', "
                    + "bi_date = '%s' ") %(
                        info.cookie, info.score,
                        info.noticesleft, lnsql, datesql
                    ))
                + ("WHERE %s " %(self._where))
                + ("AND address = '%s'" %( self.escape(member) )))



# this function can be plugged into Mailman.MailList.Save
# it saves a copy of a few list's attributes into a database
def SaveToDb(self,dict):
    query = 'REPLACE lists (listname,moderation,advertised,new_member_options,subscribe_policy,host_name,description,info,count) ' \
        " VALUES ('%s','%s','%s','%s','%s','%s','%s','%s','%s')" % (\
        self.internal_name(), \
        self.default_member_moderation, \
        self.advertised, \
        self.new_member_options, \
        self.subscribe_policy, \
        self.host_name, \
        self.escape(self.description), \
        self.escape(self.info), \
        self.getMembersCount() \
        )
    syslog('mysql', query)
    try:
        self.query(query)
    except Exception,e:
        syslog('mysql', 'error %s'%e)
    pass
