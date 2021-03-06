# Docker file for JuliaBox
# Version:29

FROM tanmaykm/jboxjulia:v0.3.6_16

MAINTAINER Tanmay Mohapatra

# Install additional packages required for Julia packages
RUN apt-get update \
    && apt-get install -y \
    cmake \
    gfortran \
    hdf5-tools \
    python-sympy \
    glpk-utils \
    libnlopt0 \
    imagemagick \
    inkscape \
    gettext \
    && apt-get clean

# Sundials
RUN apt-get install -y \
    libsundials-cvode1 \
    libsundials-cvodes2 \
    libsundials-ida2 \
    libsundials-idas0 \
    libsundials-kinsol1 \
    libsundials-nvecserial0 \
    libsundials-serial \
    libsundials-serial-dev \
    && apt-get clean

# NLopt
RUN apt-get install -y \
    libnlopt-dev \
    && apt-get clean

# Ipopt
RUN mkdir ipopt; cd ipopt; wget  http://www.coin-or.org/download/source/Ipopt/Ipopt-3.11.7.tgz; \
    tar -xzf Ipopt-3.11.7.tgz; cd Ipopt-3.11.7; \
    cd ThirdParty/Blas; ./get.Blas; ./configure --prefix=/usr/local --disable-shared --with-pic; make install; cd ../..; \
    cd ThirdParty/Lapack; ./get.Lapack; ./configure --prefix=/usr/local --disable-shared --with-pic; make install; cd ../..; \
    cd ThirdParty/Mumps; ./get.Mumps; cd ../..; \
    ./configure --prefix=/usr/local --enable-dependency-linking --with-blas=/usr/local/lib/libcoinblas.a --with-lapack=/usr/local/lib/libcoinlapack.a; \
    make install; \
    echo "/usr/local/lib" > /etc/ld.so.conf.d/ipopt.conf; ldconfig; \
    cd ../..; \
    rm -rf ipopt

# Cbc
RUN mkdir cbc; cd cbc; wget http://www.coin-or.org/download/source/Cbc/Cbc-2.8.12.tgz; \
    tar -xzf Cbc-2.8.12.tgz; cd Cbc-2.8.12; \
    ./configure --prefix=/usr/local --enable-dependency-linking --without-blas --without-lapack --enable-cbc-parallel; \
    make install; \
    echo "/usr/local/lib" > /etc/ld.so.conf.d/cbc.conf; ldconfig; \
    cd ../..; \
    rm -rf cbc

# MPI
RUN apt-get install -y \
    openmpi-bin \
    libopenmpi-dev \
    && apt-get clean

# Stan
RUN mkdir stan; cd stan; wget https://github.com/stan-dev/cmdstan/releases/download/v2.5.0/cmdstan-2.5.0.tar.gz; \
    tar -xzvf cmdstan-2.5.0.tar.gz; mv cmdstan /usr/share/cmdstan; \
    (cd /usr/share/cmdstan && make build); \
    echo "export CMDSTAN_HOME=/usr/share/cmdstan" > /etc/profile.d/cmdstan.sh; \
    chmod 755 /etc/profile.d/cmdstan.sh; \
    cd ..; \
    rm -rf stan

ENV PATH /usr/local/texlive/2014/bin/x86_64-linux:/usr/local/bin:/usr/bin:/bin:/usr/games:/sbin:/usr/sbin

# Cairo
RUN apt-get install -y \
    gettext \
    libpango1.0-dev \
    libpango1.0-0 \
    libgvc6 \
    graphviz \
    libgraphviz-dev \
    && apt-get clean

# Nemo
RUN apt-get install -y \
    m4 \
    && apt-get clean

# SymPy
RUN pip install --upgrade sympy

RUN mkdir mpir; cd mpir; wget http://mpir.org/mpir-2.7.0-alpha11.tar.bz2; \
    tar -xvf mpir-2.7.0-alpha11.tar.bz2; cd mpir-2.7.0; \
    ./configure M4=/usr/bin/m4 --enable-gmpcompat --disable-static --enable-shared; \
    make; make install; \
    cd ../..; \
    rm -rf mpir

RUN mkdir mpfr; cd mpfr; wget http://www.mpfr.org/mpfr-current/mpfr-3.1.2.tar.bz2; \
    tar -xvf mpfr-3.1.2.tar.bz2; cd mpfr-3.1.2; \
    ./configure --with-gmp=/usr/local --disable-static --enable-shared; \
    make; make install; \
    cd ../..; \
    rm -rf mpfr

RUN mkdir flint2; cd flint2; git clone https://github.com/wbhart/flint2.git; \
    cd flint2; \
    ./configure --disable-static --enable-shared --with-mpir --with-mpfr; \
    make; make install; \
    cd ../..; \
    rm -rf flint2

# add juser
# create group and user with specific ids if required on systems where the user running juliabox is not the first user
RUN groupadd juser \
    && useradd -m -d /home/juser -s /bin/bash -g juser -G staff juser \
    && echo "export HOME=/home/juser" >> /home/juser/.bashrc

USER juser
ENV HOME /home/juser
ENV PATH /usr/local/texlive/2014/bin/x86_64-linux:/usr/local/bin:/usr/bin:/bin:/sbin:/usr/sbin
WORKDIR /home/juser

# 4200: http port for console
# 8000: http port for tornado
# 8998: ipython port for julia
EXPOSE  4200 8000 8998

ENTRYPOINT /usr/bin/supervisord -n -c /home/juser/.juliabox/supervisord.conf -l /home/juser/.juliabox/supervisord.log -j /home/juser/.juliabox/supervisord.pid -q /home/juser/.juliabox
