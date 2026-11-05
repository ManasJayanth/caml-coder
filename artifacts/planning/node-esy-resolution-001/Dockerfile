FROM ocaml-sft-toolchain-probe:001
USER 1000:1000
COPY --chown=1000:1000 node.tar.xz esy.tgz /home/opam/assets/
RUN cd /home/opam/assets && printf '%s  %s\n' 'cc2f601cee82d9a5a233302fe307abc600727035fd7d2c3a3571755989e95008' node.tar.xz | sha256sum -c - && printf '%s  %s\n' '1ff1f8a831795b4737f0921897ee1abd245bce787133c8ecb5e98d6506e2d68356fc8556ed209e8f15db5519f3af74f34219b5974a9582362f657150278d322a' esy.tgz | sha512sum -c -
RUN mkdir /home/opam/node /home/opam/esy && tar -xJf /home/opam/assets/node.tar.xz --strip-components=1 -C /home/opam/node && tar -xzf /home/opam/assets/esy.tgz --strip-components=1 -C /home/opam/esy
ENV PATH=/home/opam/node/bin:/home/opam/esy/bin:/home/opam/.opam/5.5/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
RUN cd /home/opam/esy && node postinstall.js && node --version && esy --version
