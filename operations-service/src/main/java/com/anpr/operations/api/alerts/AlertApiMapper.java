package com.anpr.operations.api.alerts;

import org.mapstruct.Mapper;
import org.mapstruct.ReportingPolicy;
import org.springframework.data.domain.Page;
import com.anpr.operations.api.generated.model.AlertPage;
import com.anpr.operations.api.generated.model.AlertResponse;
import com.anpr.operations.api.generated.model.PageMeta;
import com.anpr.operations.internal.alerts.Alert;

@Mapper(componentModel = "spring", unmappedTargetPolicy = ReportingPolicy.ERROR)
public interface AlertApiMapper {
    AlertResponse toResponse(Alert alert);

    default AlertPage toPage(Page<Alert> page) {
        return new AlertPage()
                .items(page.map(this::toResponse).getContent())
                .page(new PageMeta()
                        .page(page.getNumber())
                        .size(page.getSize())
                        .totalElements(page.getTotalElements())
                        .totalPages(page.getTotalPages()));
    }
}
