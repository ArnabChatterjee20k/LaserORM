### Why separate model and schema classes and not having a base?
Model working via hooking into class creation life cycle where we we highly depends on defining a metaclass
Schema working via using dataclass

Both are having separate paradigm having similar methods
TODO: having a better model to represent them with a base -> might abstracting the common methods into a separate kind of stuff???