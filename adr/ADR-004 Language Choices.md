## ADR-004 Language and Associated Choices

### Decision:

The backend tile preparation pipeline will use the latest LTS python runtime and the minimal set of libraries needed. The web (browser) frontend will use javascript, leveraging recent library and runtime capabilities like ecmascript modules.

We should seek to import only external libraries that we are reasonably certain will reduce significant coding effort. Do not use third party libraries to eliminate or replace small amounts (\<100 lines) of code. In these instances, we prefer to write our own code with tests. External libraries *should* be used in instances where significant effort can be saved, for example `lit` for web components, and third party tiff reading libraries in python.

### Impacts

It is expected that different repositories in this project will use different runtimes, test tools, static analysis tools, etc. ADRs and top level specifications that drive development will need to be written at a high enough level that they can be implemented in multiple languages as needed.

### Reasoning

We expect that certain aspects of the pipeline layer will require more advanced numerical processing that benefit from python's extensive libraries and community. JS is a natural, native, choice for browser applications and recently supported ecmascript features lessen the need for additional layers like typescript.