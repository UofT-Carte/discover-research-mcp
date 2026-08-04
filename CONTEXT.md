# Context

The domain language of this project. Terms are added when a decision turns on
one, not up front.

## Scholar

A person with a profile on the Discover Research portal — U of T faculty and
researchers. Identified two ways, and **both are accepted everywhere a scholar
id is taken**: the numeric id (`17964`) and the URL-style id
(`17964-michael-guerzhoy`). Prefer *scholar* over "user", which is the portal's
own word for the same thing and means something else to us.

## Linked object

A record the portal attaches to a scholar: a **publication**, a **grant**, or a
**professional activity**. The portal serves them from a single endpoint shape,
`/<kind>/linkedTo`, and reports them together under `linkedObjectIds` on a
profile.

The term is what makes one fetch module reasonable for kinds that are otherwise
unrelated: it names the thing they actually share, which is the request and
paging protocol rather than anything about publications or grants themselves.

Only publications and grants have tools today. Professional activities are
counted on a profile but not listed.
