"""The free prefilter: reject what does not need a model to reject.

Every new posting passes through here before anything is spent on it. Rules are
declared in `config/rules.yaml`, evaluated in declaration order, first rejection
wins - and the deciding rule is recorded, so every rejection can be explained
rather than guessed at.

The rules are data, not code. Adding, disabling or reordering one is a YAML edit;
adding a new *kind* of rule is one function in the registry here.

See PRD section 8.3[3].
"""
