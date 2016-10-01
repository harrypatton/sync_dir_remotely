#!/usr/bin/python2.7
#
# This program continuously one-way synchronises one local directory
# into a remote machine.
#
# LocalClient ==> RemoteServer
#
# Usage:
#

#########################################################
# Imports
#########################################################
import argparse
import datetime
import json
import os
import os.path
import re
import socket
import struct
import time



#########################################################
# Functions
#########################################################
def parse_args():
  parser = argparse.ArgumentParser(description='Synchronise a dir remotely.')
  parser.add_argument(
      '-m',
      '--mode',
      required=True,
      type=str,
      choices=('remote', 'local'),
      help='Mode to run this script in.',
  )

  parser.add_argument(
      '-p',
      '--port',
      default=8082,
      type=int,
      help='Remote server listen port.',
  )

  parser.add_argument(
      '-v',
      '--verbosity',
      default=LOG_LEVELS.index('info'),
      type=int,
      choices=range(len(LOG_LEVELS)),
      help='Remote server listen port. levels=[{}]'.format(
          ', '.join(['{}={}'.format(LOG_LEVELS[i], i) \
              for i in range(len(LOG_LEVELS))])),
  )

  parser.add_argument(
      '-r',
      '--remote',
      default='localhost',
      type=str,
      help='Remote machine to connect to.',
  )

  args = parser.parse_args()
  return args



#########################################################
# Remote Server Classes
#########################################################
class RemoteServer(object):
  def __init__(self, args):
    self.log = Logger(type(self).__name__)
    self.log.info('Initing...')
    self._args = args
    self._msgHandler = MessageHandler()

  def __enter__(self):
    self.log.info('Initializing...')
    self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    self._socket.bind(('', self._args.port))
    return self

  def run(self):
    self.log.info('Running...')
    while True:
      self.log.info('Listening for incoming connections in port [{}]...'.format(
          self._args.port))
      self._socket.listen(1)
      connection, address = self._socket.accept()
      connection.settimeout(30.0) # seconds
      self.log.info('Accepted connection from address: [{}]'.format(
          str(address)))
      with StreamHandler(connection) as streamHandler:
        while True:
          message = streamHandler.recvMessage()
          if None == message:
            break
          else:
            response = self._msgHandler.handleMessage(message)
            assert response.type % 2 == 1, \
                ('All responses must be of an odd type. '
                    'Found type [{}] instead.').format(response.type)
            streamHandler.sendMessage(response)

  def __exit__(self, exc_type, exc_value, traceback):
    self.log.info('Exiting...')
    if exc_type and exc_value and traceback:
      self.log.error('Received exception type=[{}] value=[{}] traceback=[{}]'\
          .format(exc_type, exc_value, traceback))
    if self._socket:
      self._socket.close()
      self._socket = None



#########################################################
# Local Client Classes
#########################################################
class LocalClient(object):
  def __init__(self, args):
    self.log = Logger(type(self).__name__)
    self.log.info('Initializing...')
    self._args = args
    self._msgHandler = MessageHandler()

  def __enter__(self):
    self.log.info('Entering...')
    self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    self._socket.settimeout(1.0) # seconds
    remote = self._args.remote
    port = self._args.port
    self.log.info('Trying to connect to [{}:{}]'.format(remote, port))
    self._socket.connect((remote, port))
    self.log.info('Successfully connected to [{}:{}]'.format(
        remote, port))
    return self

  def run(self):
    self.log.info('Running...')
    with StreamHandler(self._socket) as streamHandler:
      while True:
        request = Message(MessageType.PING_REQUEST)
        streamHandler.sendMessage(request)
        try:
          response = streamHandler.recvMessage()
          self._msgHandler.handleMessage(response)
        except socket.timeout:
          # Nothing to receive from the server.
          pass

  def __exit__(self, exc_type, exc_value, traceback):
    self.log.info('Exiting...')
    if self._socket:
      self._socket.close()
      self._socket = None



#########################################################
# Common Classes
#########################################################
class Logger(object):
  LEVEL = 4

  def __init__(self, log_name):
    self._name = log_name

  def verbose(self, msg):
    self._log(4, msg)

  def debug(self, msg):
    self._log(3, msg)

  def info(self, msg):
    self._log(2, msg)

  def warn(self, msg):
    self._log(1, msg)

  def error(self, msg):
    self._log(0, msg)

  def _log(self, level, msg):
    if level > Logger.LEVEL:
      return

    ts = datetime.datetime.fromtimestamp(time.time()) \
        .strftime('%Y-%m-%d %H:%M:%S.%f')
    level = LOG_LEVELS[level].upper()[0]
    print '[{}][{}]<{}> {}'.format(level, ts, self._name, msg)


class StreamHandler(object):
  def __init__(self, socket):
    self.log = Logger(type(self).__name__)
    self._socket = socket
    self._buffer = ''
    self._serde = MessageSerde()

  def __enter__(self):
    self.log.info('Entering...')
    return self

  def recvMessage(self):
    self.log.info('Receiving message...')
    while True:
      data = self._socket.recv(1024)
      datal = len(data)
      if datal == 0:
        self.log.info('Remote client disconnected.')
        return None
      elif datal > 0:
        self.log.info('Received [{}] bytes.'.format(datal))
        self._buffer += data
        message, unused = self._serde.deserialise(self._buffer)
        unused_bytes = len(unused)
        used_bytes = len(self._buffer) - unused_bytes
        self._buffer = unused
        self.log.verbose(
            'Received message_type=[{}] used_bytes=[{}] unused_bytes=[{}].'\
                .format(message.type, used_bytes, unused_bytes))
        return message
      else:
        assert False, 'Should never get here!!! recv_bytes=[{}]'.format(datal)

  def __exit__(self, exc_type, exc_value, traceback):
    self.log.info('Exiting...')
    if self._socket:
      self._socket.close()
      self._socket = None

  def sendMessage(self, message):
    data = self._serde.serialise(message)
    self.log.info('Sending message of type [{}] and size [{}] bytes...'\
        .format(message.type, len(data)))
    self._socket.sendall(data)


class MessageType(object):
  """ All Response types must be odd numbered """
  PING_REQUEST = 0
  PING_RESPONSE = 1

class Message(object):
  def __init__(self, message_type):
    self.type = message_type
    self.body = {}


class MessageSerde(object):
  def __init__(self):
    self.log = Logger(type(self).__name__)

  def serialise(self, message):
    """ Returns a list of bytes containing the serialised msg/ """
    body = json.dumps(message.body)
    header = struct.pack('>ii', message.type, len(body))
    return header + body

  def deserialise(self, input):
    """ Returns a tuple (Message, UnusedBytesList) """
    self.log.info('Deserialising input of [{}] bytes...'.format(len(input)))
    header_size = 8
    if len(input) < header_size:
      self.log.verbose('Input buffer has less than 8 bytes.')
      return (None, input)
    message_type, body_size = struct.unpack('>ii', input[0:header_size])
    message = Message(message_type)
    total_size = header_size + body_size
    if len(input) < total_size:
      self.log.verbose('Input buffer has less than [{}] bytes.'.format(
          total_size))
      return (None, input)
    if body_size > 0:
      raw_body = input[header_size:total_size]
      message.body.update(json.loads(raw_body))
    return (message, input[total_size:])


class MessageHandler(object):
  def __init__(self):
    self.log = Logger(type(self).__name__)

  def handleMessage(self, message):
    self.log.info('Handling message of type: [{}]'.format(message.type))
    # Odd numbered MessageType's are responses.
    if message.type % 2 == 1:
      return None
    # TODO(ruibm): Do the proper thing instead of just mirroring.
    response = Message(MessageType.PING_RESPONSE)
    self.log.info("Responding with message of type: [{}]".format(response.type))
    return response


class DirCrawler(object):
  def __init__(self, root_dir, exclude_list=[]):
    self.log = Logger(type(self).__name__)
    self._dir = root_dir
    self._excludes = [re.compile(pattern) for pattern in exclude_list]

  def crawl(self):
    self.log.info('Starting to crawl [{}]...'.format(self._dir))
    all_files = []
    for root, dirs, files in os.walk(self._dir):
      for f in files:
        rel_path = os.path.join(root, f)
        # self.log.verbose('Found file [{}]'.format(rel_path))
        if not self._is_excluded(rel_path):
          all_files.append(rel_path)
    self.log.info('Crawl found a total of [{}] files...'.format(len(all_files)))
    print all_files
    return all_files

  def _is_excluded(self, path):
    for regex in self._excludes:
      if None != regex.match(path):
        return True
    return False






#########################################################
# Constants
#########################################################
LOG_LEVELS = ('error', 'warn', 'info', 'debug', 'verbose')
LOG = Logger('main')



#########################################################
# Main
#########################################################
def main():
  args = parse_args()
  Logger.LEVEL = args.verbosity
  LOG.info('Mode: [{}]'.format(args.mode))
  if args.mode == 'remote':
    with RemoteServer(args) as server:
      server.run()
  else:
    with LocalClient(args) as client:
      client.run()


if __name__ == '__main__':
  main()

