package com.anpr.devicemanagement.api.images;

import com.anpr.devicemanagement.api.generated.ImagesApi;
import com.anpr.devicemanagement.api.generated.model.CreateImageUploadUrlsRequest;
import com.anpr.devicemanagement.api.generated.model.ImageUploadUrlsResponse;
import com.anpr.devicemanagement.internal.images.ImageUploadService;
import com.anpr.devicemanagement.shared.security.CurrentCaller;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
public class ImagesController implements ImagesApi {
    private final ImageUploadService imageUploadService;
    private final ImagesApiMapper mapper;
    private final CurrentCaller currentCaller;

    @Override
    public ResponseEntity<ImageUploadUrlsResponse> createImageUploadUrls(CreateImageUploadUrlsRequest request) {
        return ResponseEntity.ok(mapper.toResponse(
                imageUploadService.createUploadUrls(currentCaller.get(), mapper.toFrames(request.getFrames()))));
    }
}
