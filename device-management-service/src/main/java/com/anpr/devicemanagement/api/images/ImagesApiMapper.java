package com.anpr.devicemanagement.api.images;

import com.anpr.devicemanagement.api.common.TimeMapping;
import com.anpr.devicemanagement.api.generated.model.FrameToUpload;
import com.anpr.devicemanagement.api.generated.model.ImageUpload;
import com.anpr.devicemanagement.api.generated.model.ImageUploadUrlsResponse;
import com.anpr.devicemanagement.internal.images.Frame;
import com.anpr.devicemanagement.internal.images.PresignedUpload;
import org.mapstruct.Mapper;
import org.mapstruct.ReportingPolicy;

import java.util.List;

@Mapper(componentModel = "spring", uses = TimeMapping.class, unmappedTargetPolicy = ReportingPolicy.ERROR)
public interface ImagesApiMapper {

    List<Frame> toFrames(List<FrameToUpload> frames);

    ImageUpload toUpload(PresignedUpload upload);

    default ImageUploadUrlsResponse toResponse(List<PresignedUpload> uploads) {
        return new ImageUploadUrlsResponse().uploads(uploads.stream().map(this::toUpload).toList());
    }
}
