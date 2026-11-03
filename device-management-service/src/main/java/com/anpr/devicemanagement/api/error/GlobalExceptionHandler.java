package com.anpr.devicemanagement.api.error;

import com.anpr.devicemanagement.shared.error.BusinessException;
import com.anpr.devicemanagement.shared.error.ConflictException;
import com.anpr.devicemanagement.shared.error.ErrorCodes;
import com.anpr.devicemanagement.shared.error.FieldViolation;
import com.anpr.devicemanagement.shared.error.ForbiddenException;
import com.anpr.devicemanagement.shared.error.NotFoundException;
import com.anpr.devicemanagement.shared.error.UnauthorizedException;
import com.anpr.devicemanagement.shared.error.ValidationException;
import com.anpr.devicemanagement.shared.tracing.TraceId;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ProblemDetail;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.validation.FieldError;
import org.springframework.web.ErrorResponse;
import org.springframework.web.HttpMediaTypeNotAcceptableException;
import org.springframework.web.HttpMediaTypeNotSupportedException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.HandlerMethodValidationException;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Every error is an RFC 9457 problem with {@code code} and {@code requestId} (the trace id); validation errors add
 * {@code fields[]}. Responses never reveal internals (classes, tables, AWS resources).
 */
@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {
    /** The position of the item in a batch, from a field path such as {@code metrics[3].cpuUsagePercent}. */
    private static final Pattern BATCH_INDEX = Pattern.compile("^\\w+\\[(\\d+)]");

    /** Bean Validation constraint names translated to the field codes the ingest Lambda uses too. */
    private static final Map<String, String> FIELD_CODES = Map.of(
            "NotNull", ErrorCodes.REQUIRED,
            "Min", ErrorCodes.RANGE,
            "Max", ErrorCodes.RANGE,
            "DecimalMin", ErrorCodes.RANGE,
            "DecimalMax", ErrorCodes.RANGE,
            "Size", ErrorCodes.SIZE,
            "Pattern", ErrorCodes.PATTERN);

    @ExceptionHandler(NotFoundException.class)
    ProblemDetail handleNotFound(NotFoundException ex) {
        return refused(HttpStatus.NOT_FOUND, ex);
    }

    @ExceptionHandler(ConflictException.class)
    ProblemDetail handleConflict(ConflictException ex) {
        return refused(HttpStatus.CONFLICT, ex);
    }

    @ExceptionHandler(ForbiddenException.class)
    ProblemDetail handleForbidden(ForbiddenException ex) {
        return refused(HttpStatus.FORBIDDEN, ex);
    }

    @ExceptionHandler(UnauthorizedException.class)
    ProblemDetail handleUnauthorized(UnauthorizedException ex) {
        return refused(HttpStatus.UNAUTHORIZED, ex);
    }

    @ExceptionHandler(ValidationException.class)
    ProblemDetail handleValidation(ValidationException ex) {
        ProblemDetail problem = refused(HttpStatus.BAD_REQUEST, ex);
        problem.setProperty("fields", ex.getViolations().stream().map(GlobalExceptionHandler::toField).toList());
        return problem;
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    ProblemDetail handleBodyValidation(MethodArgumentNotValidException ex) {
        List<FieldViolation> violations = ex.getBindingResult().getFieldErrors().stream()
                .map(GlobalExceptionHandler::toViolation)
                .toList();
        return handleValidation(new ValidationException(violations));
    }

    @ExceptionHandler({
            HandlerMethodValidationException.class,
            MethodArgumentTypeMismatchException.class,
            MissingServletRequestParameterException.class,
            HttpMessageNotReadableException.class})
    ProblemDetail handleBadRequest(Exception ex) {
        log.atInfo().addKeyValue("exception", ex.getClass().getSimpleName()).log("Invalid request");
        return problem(HttpStatus.BAD_REQUEST, ErrorCodes.INVALID_REQUEST, "Invalid request");
    }

    @ExceptionHandler({
            NoResourceFoundException.class,
            HttpRequestMethodNotSupportedException.class,
            HttpMediaTypeNotSupportedException.class,
            HttpMediaTypeNotAcceptableException.class})
    ProblemDetail handleUnsupported(Exception ex) {
        HttpStatusCode status = ((ErrorResponse) ex).getStatusCode();
        return problem(status, ErrorCodes.INVALID_REQUEST, "Request not supported");
    }

    @ExceptionHandler(Exception.class)
    ProblemDetail handleUnexpected(Exception ex) {
        log.error("Unexpected error", ex);
        return problem(HttpStatus.INTERNAL_SERVER_ERROR, ErrorCodes.INTERNAL_ERROR, "Unexpected error");
    }

    private static ProblemDetail refused(HttpStatusCode status, BusinessException ex) {
        log.atInfo().addKeyValue("code", ex.getCode()).addKeyValue("status", status.value()).log("Request refused");
        return problem(status, ex.getCode(), ex.getMessage());
    }

    private static ProblemDetail problem(HttpStatusCode status, String code, String detail) {
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(status, detail);
        problem.setProperty("code", code);
        problem.setProperty("requestId", TraceId.current().orElseGet(() -> UUID.randomUUID().toString()));
        return problem;
    }

    private static FieldViolation toViolation(FieldError error) {
        Matcher index = BATCH_INDEX.matcher(error.getField());
        return new FieldViolation(
                index.find() ? Integer.valueOf(index.group(1)) : null,
                error.getField(),
                FIELD_CODES.getOrDefault(error.getCode(), String.valueOf(error.getCode()).toUpperCase()),
                String.valueOf(error.getDefaultMessage()));
    }

    /** The order of the contract (index, field, code, message); index only when the error is about a batch item. */
    private static Map<String, Object> toField(FieldViolation violation) {
        Map<String, Object> field = new LinkedHashMap<>();
        if (violation.index() != null) {
            field.put("index", violation.index());
        }
        field.put("field", violation.field());
        field.put("code", violation.code());
        field.put("message", violation.message());
        return field;
    }
}
