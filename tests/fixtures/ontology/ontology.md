# Ontology

Kinds and relations of this vault.

```yaml
kinds:
  mission:    {}
  rover:      {part_of: mission, has: [instrument]}
  instrument: {part_of: [rover, mission]}
  Bad Kind:   {}
```
