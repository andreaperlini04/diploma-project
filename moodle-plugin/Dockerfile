FROM php:8.3-apache

# Dipendenze di sistema
RUN apt-get update && apt-get install -y \
    git \
    unzip \
    zip \
    curl \
    libpng-dev \
    libjpeg-dev \
    libfreetype6-dev \
    libicu-dev \
    libxml2-dev \
    libzip-dev \
    libonig-dev \
    libcurl4-openssl-dev \
    libpq-dev \
    default-mysql-client \
    locales \
    && rm -rf /var/lib/apt/lists/*

# L'immagine base non genera alcun locale oltre a C. PHPUnit richiede
# en_AU.UTF-8 e si ferma con CONFIGERROR se manca: si veda get_locale_name()
# in lib/classes/test/phpunit/phpunit_util.php, dove il valore è fisso.
RUN sed -i 's/^# *en_AU\.UTF-8 UTF-8/en_AU.UTF-8 UTF-8/' /etc/locale.gen \
    && locale-gen

RUN docker-php-ext-configure gd \
    --with-freetype \
    --with-jpeg

# Estensioni PHP richieste da Moodle
RUN docker-php-ext-install \
    mysqli \
    pdo \
    pdo_mysql \
    intl \
    gd \
    zip \
    soap \
    exif \
    opcache \
    curl \
    xml \
    mbstring

RUN a2enmod rewrite headers expires ssl

# Composer da immagine ufficiale, per la riproducibilità della build
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer

# Composer gira come root nell'immagine: senza questa variabile emette un
# avviso a ogni invocazione e in alcuni casi attende una conferma.
ENV COMPOSER_ALLOW_SUPERUSER=1

WORKDIR /var/www/html

# Prima i soli file delle dipendenze: il layer resta in cache finché non
# cambiano, quindi una modifica al codice non fa riscaricare i pacchetti.
COPY ./moodle/composer.json ./moodle/composer.lock ./

# codeload.github.com limita per IP e su runner condiviso risponde 429 a metà
# del download: meno parallelismo, ritentativi con attesa crescente e infine
# recupero da git. L'autoloader si genera sotto, richiede i sorgenti.
RUN set -eu; \
    for i in 1 2 3; do \
        if COMPOSER_MAX_PARALLEL_HTTP=4 composer install \
                --no-dev --no-autoloader --no-interaction; then \
            exit 0; \
        fi; \
        echo "tentativo $i non riuscito, attendo $((i * 20))s"; \
        sleep $((i * 20)); \
    done; \
    echo "download dagli archivi non riuscito, passo al recupero da git"; \
    composer install --no-dev --no-autoloader --no-interaction --prefer-source; \
    find /var/www/html/vendor -type d -name .git -prune -exec rm -rf {} +

COPY ./moodle /var/www/html

# Autoloader a sorgenti completi. Non richiede rete.
RUN composer dump-autoload --no-dev --optimize

# Radice web su public/, come richiesto da Moodle 5.x
ENV APACHE_DOCUMENT_ROOT=/var/www/html/public

RUN sed -ri -e 's!/var/www/html!${APACHE_DOCUMENT_ROOT}!g' \
    /etc/apache2/sites-available/*.conf \
    /etc/apache2/apache2.conf \
    /etc/apache2/conf-available/*.conf

COPY php.ini /usr/local/etc/php/

RUN chown -R www-data:www-data /var/www/html

# Dataroot fuori dalla radice web, scrivibile da Apache
RUN mkdir -p /var/www/moodledata \
    && chown -R www-data:www-data /var/www/moodledata

EXPOSE 80