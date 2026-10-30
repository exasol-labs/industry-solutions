FROM confluentinc/cp-kafka-connect:7.5.9 AS confluent_connect

FROM debezium/connect:2.4.2.Final

USER root

RUN mkdir -p /kafka/connect/confluent-avro

COPY --from=confluent_connect /usr/share/java/confluent-common /kafka/connect/confluent-avro/
COPY --from=confluent_connect /usr/share/java/rest-utils /kafka/connect/confluent-avro/
COPY --from=confluent_connect /usr/share/java/schema-registry /kafka/connect/confluent-avro/
COPY --from=confluent_connect /usr/share/java/kafka-serde-tools /kafka/connect/confluent-avro/

RUN chmod -R a+rX /kafka/connect/confluent-avro
