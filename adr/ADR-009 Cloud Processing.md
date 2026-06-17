ADR-009 Direction on cloud processing

### Decision:

- We will use Google Cloud Platform (GCP) for cloud based processing of map data
- We will primarily used container based deployments and avoid, to the extent reasonable, using bare VMs with software deployed directly on them
- We will host web facing components of the application on CloudFlare


### Impacts

- Applications that we plan on running in a cloud environment will require a dockerfile to define how they are containerized. This includes many of the applications in the third-party-static-data/utility folder
- We'll continue using our existing scripts as-is to deploy the application and media we generate locally. We will also need to develop tooling to move data from GCP to Cloudflare as needed.
- We will, to the extent reasonable, use tools like GCP Cloud Run and Cloudflare Workers instead of GCP's virtual machines.

### Reasoning

- We're going to use GCP for my own person benefit to help learn another set of cloud tooling. We will also choose GCP due to its generous free tier including an amount of always free egrees. 
- We're going to use container based deployments to minimize the hand-roll configuration of virtual machines. Containers also let us bring along newer versions of software, like OSGEO GDAL, that is often not fully updated on cloud platforms.
- At this point in time, the existing web-tilelayer application is hosted on CloudFlare and it will remain there for now. This may change in the future, but we should not plan on that. 