def productExceptSelf(nums: list[int]) -> list[int]:
    length = len(nums)
    # Initialize the output array with 1s
    output = [1] * length

    # Step 1: Compute prefix products
    prefix = 1
    for i in range(length):
        output[i] = prefix
        prefix *= nums[i]

    # Step 2: Compute suffix products on the fly and combine
    suffix = 1
    for i in range(length - 1, -1, -1):
        output[i] *= suffix
        suffix *= nums[i]

    return output

productExceptSelf([1,2,3,4])