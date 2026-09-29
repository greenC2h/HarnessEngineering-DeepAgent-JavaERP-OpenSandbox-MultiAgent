package com.motorparts.common;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.DeserializationContext;
import com.fasterxml.jackson.databind.JsonDeserializer;

import java.io.IOException;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;

public class CustomLocalDateTimeDeserializer extends JsonDeserializer<LocalDateTime> {

    private static final DateTimeFormatter ISO_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSS");

    @Override
    public LocalDateTime deserialize(JsonParser p, DeserializationContext ctxt) throws IOException {
        String value = p.getValueAsString();
        if (value == null || value.isEmpty()) {
            return null;
        }

        String cleanedValue = value.trim();

        if (cleanedValue.endsWith("Z")) {
            cleanedValue = cleanedValue.substring(0, cleanedValue.length() - 1);
        }

        int tIndex = cleanedValue.indexOf('T');
        if (tIndex > 0) {
            String afterT = cleanedValue.substring(tIndex + 1);
            if (afterT.contains("+") || afterT.contains("-")) {
                cleanedValue = cleanedValue.substring(0, tIndex);
            }
        }

        if (cleanedValue.length() > 23) {
            cleanedValue = cleanedValue.substring(0, 23);
        }

        return LocalDateTime.parse(cleanedValue, ISO_FORMATTER);
    }
}