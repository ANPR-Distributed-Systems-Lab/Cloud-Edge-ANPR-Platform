package com.anpr.operations.api.error;

import com.anpr.operations.shared.error.BadRequestException;
import com.anpr.operations.shared.error.ConflictException;
import com.anpr.operations.shared.error.ErrorCodes;
import com.anpr.operations.shared.error.FieldCodes;
import com.anpr.operations.shared.error.NotFoundException;
import com.anpr.operations.shared.error.UnauthorizedException;
import com.anpr.operations.shared.tracing.TraceId;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ProblemDetail;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.orm.ObjectOptimisticLockingFailureException;
import org.springframework.web.ErrorResponse;
import org.springframework.web.HttpMediaTypeNotSupportedException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.HandlerMethodValidationException;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

import java.util.Map;
import java.util.UUID;

@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {
    /** Bean Validation constraint names translated to the field codes shared with device-management and ingest. */
    private static final Map<String, String> FIELD_CODES = Map.of(
            "NotNull", FieldCodes.REQUIRED.name(),
            "Min", FieldCodes.RANGE.name(),
            "Max", FieldCodes.RANGE.name(),
            "DecimalMin", FieldCodes.RANGE.name(),
            "DecimalMax", FieldCodes.RANGE.name(),
            "Size", FieldCodes.SIZE.name(),
            "Pattern", FieldCodes.PATTERN.name());

    @ExceptionHandler(NotFoundException.class)
    ProblemDetail handleNotFound(NotFoundException ex) {
        return problem(HttpStatus.NOT_FOUND, ex.getCode(), ex.getMessage());
    }

    @ExceptionHandler(ConflictException.class)
    ProblemDetail handleConflict(ConflictException ex) {
        return problem(HttpStatus.CONFLICT, ex.getCode(), ex.getMessage());
    }

    @ExceptionHandler(BadRequestException.class)
    ProblemDetail handleInvalidInput(BadRequestException ex) {
        return problem(HttpStatus.BAD_REQUEST, ex.getCode(), ex.getMessage());
    }

    @ExceptionHandler(UnauthorizedException.class)
    ProblemDetail handleUnauthorized(UnauthorizedException ex) {
        return problem(HttpStatus.UNAUTHORIZED, ex.getCode(), ex.getMessage());
    }

    @ExceptionHandler(ObjectOptimisticLockingFailureException.class)
    ProblemDetail handleOptimisticLock(ObjectOptimisticLockingFailureException ex) {
        return problem(HttpStatus.CONFLICT, ErrorCodes.CONCURRENT_MODIFICATION,
                "Resource was modified by someone else");
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    ProblemDetail handleBodyValidation(MethodArgumentNotValidException ex) {
        ProblemDetail problem = problem(HttpStatus.BAD_REQUEST, ErrorCodes.VALIDATION_FAILED,
                "Request validation failed");
        problem.setProperty("fields", ex.getBindingResult().getFieldErrors().stream()
                .map(error -> Map.of(
                        "field", error.getField(),
                        "code", FIELD_CODES.getOrDefault(error.getCode(), String.valueOf(error.getCode()).toUpperCase()),
                        "message", String.valueOf(error.getDefaultMessage())))
                .toList());
        return problem;
    }

    @ExceptionHandler({
            HandlerMethodValidationException.class,
            MethodArgumentTypeMismatchException.class,
            MissingServletRequestParameterException.class,
            HttpMessageNotReadableException.class})
    ProblemDetail handleBadRequest(Exception ex) {
        return problem(HttpStatus.BAD_REQUEST, ErrorCodes.INVALID_REQUEST, "Invalid request");
    }

    @ExceptionHandler({
            NoResourceFoundException.class,
            HttpRequestMethodNotSupportedException.class,
            HttpMediaTypeNotSupportedException.class})
    ProblemDetail handleUnsupported(Exception ex) {
        HttpStatusCode status = ((ErrorResponse) ex).getStatusCode();
        return problem(status, ErrorCodes.INVALID_REQUEST, "Request not supported");
    }

    @ExceptionHandler(Exception.class)
    ProblemDetail handleUnexpected(Exception ex) {
        log.error("Unexpected error", ex);
        return problem(HttpStatus.INTERNAL_SERVER_ERROR, ErrorCodes.INTERNAL_ERROR, "Unexpected error");
    }

    private ProblemDetail problem(HttpStatusCode status, ErrorCodes code, String detail) {
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(status, detail);
        problem.setProperty("code", code.name());
        problem.setProperty("requestId", TraceId.current().orElseGet(() -> UUID.randomUUID().toString()));
        return problem;
    }
}
