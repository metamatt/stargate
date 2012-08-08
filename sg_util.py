# (c) 2012 Matt Ginzton, matt@ginzton.net
#
# Utility classes and helpers for Stargate.

# Simple classes to allow attribute-style lookup of dictionary members.
def obj_to_attrdict_type(obj):
	if type(obj) == dict:
		return AttrDict(obj)
	elif type(obj) == list:
		return AttrDictList(obj)
	else:
		return obj

class AttrDictList(list):
	def __getitem__(self, name):
		item = super(AttrDictList, self).__getitem__(name)
		return obj_to_attrdict_type(item)
			
	def __iter__(self):
		for item in super(AttrDictList, self).__iter__():
			yield obj_to_attrdict_type(item)

class AttrDict(dict):
	# This handles only get, not set or del. I make no representation that
	# it works for all possible cases; just that it works well enough for
	# the uses here (wrapping read-only dictionary we read from json or yaml).
	
	# Note that we automatically convert embedded dictionaries to AttrDicts,
	# and embedded lists of dictionaries to lists of AttrDicts, on extraction
	# (as long as you use our method of extraction).
	def __getitem__(self, name):
		item = super(AttrDict, self).__getitem__(name)
		return obj_to_attrdict_type(item)
	__getattr__ = __getitem__

	def __iter__(self):
		for item in super(AttrDict, self).__iter__():
			yield obj_to_attrdict_type(item)
