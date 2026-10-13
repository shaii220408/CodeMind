package sample.service;

public class KafkaProducer {
    public void publish(String message) {
        System.out.println("Publishing notification: " + message);
    }
}
